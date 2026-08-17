# FantasyStakes — Mobile UI/UX Rev 4.2 · Global Delta

**Status:** transcription of the locked Rev 4.2 global POR as delivered in the Sprint 7 Package 1 handoff
**Date:** 2026-08-09
**Base:** `spec/SPEC_Mobile_UI_UX_Rev4_1.md` — Revision 4.1
**Scope:** global frame and shared components only

---

## 0. What this document is, and is not

Revision 4.1 is the last full UI/UX specification held in this repository. The
Rev 4.2 POR is locked, but its **global** clauses reached this repository through
the Sprint 7 Package 1 implementation handoff rather than as a specification
file. This document records those clauses verbatim so the build has a
citable source, and so a later reader can tell which parts of the shipped shell
came from Rev 4.1 and which from the Rev 4.2 delta.

It transcribes. It does not interpret, extend, or resolve. Everything in Rev 4.1
that is not listed below carries forward unchanged. Where a Rev 4.2 tab-level
clause has not yet been delivered, this document says so rather than inferring
one.

Upstream game, wager, accounting, settlement, economy and provider protocols
remain authoritative for mechanics. Rev 4.2 governs presentation only.

---

## 1. Branding

Product name:

```
FantasyStakes
```

Tagline:

```
FANTASY LEAGUES · VIRTUAL STAKES
```

League identity example:

```
CULV APPRECIATION SOCIETY
```

### Superseded by this delta

| Superseded string | Source | Replacement |
|---|---|---|
| `OUR THING · YOUR LEAGUE` | Rev4.1 §1.1 masthead tagline | `FANTASY LEAGUES · VIRTUAL STAKES` |
| `CULV Appreciation Society · Fantasy Sportsbook` | Rev4.1 §2.2 league identity | `CULV APPRECIATION SOCIETY` |

Rev4.1 conformance items 3 and 38 are superseded to the same extent, and only
to that extent.

---

## 2. Vocabulary

Betting vocabulary is intentional and is **not** sanitised. The following terms
remain in GM-facing copy:

```
ML   Spread   O/U   odds   Challenge   stake   pot   bets   wagering
```

The Virtual Credits distinction is communicated through the approved disclaimer
context below, not by stripping sportsbook language.

---

## 3. Credits disclaimer

Exact string:

```
VIRTUAL CREDITS · $ IS DISPLAY ONLY · NO CASH VALUE
```

Placement: under the applicable four-cell strip, **at most once per tab**.

A tab that summarises no position carries no strip and therefore no disclaimer.

---

## 4. Four-cell summary strips

- One reusable component across League, Action, The Week and Ledger.
- Ledger may additionally use its approved second **My Season** strip.
- Stronger value typography than Rev4.1.
- Credit and dollar values are displayed as **whole dollars, rounded to the
  nearest dollar, for presentation only**.
- Underlying Ledger and accounting values remain **exact**.

The four-cell grammar of Rev4.1 §1.4 is otherwise unchanged: four equal columns,
tile background, small grey label above a larger centred value, icon-free, with
at most one anchor or gold cell per strip.

---

## 5. Pop-outs and sheets

- One common interaction treatment where practical.
- The close **X** is always in the **upper-right** of the active sheet or card.
- This supersedes any older upper-left treatment.

> **SUPERSEDED — HISTORICAL RECORD ONLY.** The two statements immediately above
> record what Rev 4.2 decided and are left as written for that reason.
> They are no longer in force. By owner ruling the universal close control is
> **upper-left**, visually attached to the active card, sheet or modal, matching
> the Versus composer, at a minimum 44 px touch target.
> The governing statement is §25 of `FantasyStakes_UIUX_Rev4_3_FINAL_POR.md`.
> Do not implement from this paragraph.

---

## 6. Navigation

```
League · Action · Ledger · The Week · Rules & Settings
```

The bottom navigation is persistent and reachable, and does not cover tab
content.

---

## 7. Protocol safety

UI implementation does not alter domain behaviour: ledger accounting, wager
lifecycle, Dynamic/Locked semantics, escrow rules, settlement, Pool semantics,
Yahoo provider behaviour, or any other governing protocol.

In particular, and carried here only as constraints on presentation:

- Locked proposal terms are frozen per the governing Locked/Dynamic ruling.
- The Dynamic issuer Anchor is fixed; only the opponent Derived stake may
  decrease through Final Lock, per the governing rules.
- `$0` is the untouched default wager-entry state in the eventual composer.

Protocol behaviour is never inferred from the prototype. Existing specs and
tests remain authoritative where prototype text conflicts with protocol.

---

## 8. Carried, not resolved

These are open at the time of writing and are **not** decided by this document.

| Item | State |
|---|---|
| The Week's four-cell strip — which four cells | not yet specified · component ready, cells not invented |
| Ledger second `My Season` strip — which four cells | approved in principle · cells not yet specified |
| Rev 4.2 tab-level clauses for League, Action, Ledger, The Week, Rules & Settings | delivered per package, not held here |
| Top-Off Cap numeric anchor | unresolved · do not invent (carried from Rev4.1 §9) |
| Locked/Dynamic mode propagation on outgoing offers | not implemented (carried from Rev4.1 §9) |

---

## 9. Artifact integrity

The Rev 4.1 canonical prototype is retained unmodified as the historical POR
artifact:

```
spec/FantasyStakes_UIUX_Prototype_Rev4_1.html
tools/prototype/index.html
SHA-256  b2ab382f775086df469487fe5ad637757eb070e6794e8e1d8551264bd5129b88
```

Sprint 7 builds the application at `web/`, served at `/app`. It does not modify
the prototype. `test_s7_p1_ui_shell.py` asserts both files still hash to the
value above.