# FantasyStakes — Post-UPSIDE-LEFT Browser Recheck

**Package date:** 2026-08-28
**Subjects:** Action v24 · Standings + Wrap Up v8 · Account + Gear v25 · Fixture v4
**Deterministic status going in:** **166/166 PASS**, 0 failures.

---

## This is a narrow delta recheck

**The prior full visual certification remains authoritative for every untouched surface.**
This document covers only what changed on screen since it, across two passes:

- **FSR-023** (escrow reconciliation) — Wallet Ŧ138 → Ŧ94, In Play Ŧ37 → Ŧ81, two added
  ledger rows, and the Single Team Prop Pool tile becoming *entered*.
- **FSR-024** (this pass) — UPSIDE LEFT Ŧ57 → Ŧ16.14.

Nothing else was touched. Do **not** re-run the full checklist. Do **not** re-test the
deterministic spine — economics, ledger reconciliation, score chain, probability model,
GE-603 and lifecycle are certified at 166/166 and are unaffected by rendering.

If an item fails, report it as a **visual** finding. Do not edit product logic to fix a
layout problem: the economics are locked and reconciled.

**Run at 390px** (the `.phone` frame is fixed at 390 × 844), then repeat section 5 at
**360px** — Action is the only artifact with a second layout. `file://` is fine; the
artifacts are fully self-contained.

---

## 1 · Action top strip

Open **Action v24**. The four cells must read:

| Cell | Expected |
|---|---|
| WALLET | `Ŧ94` |
| WEEKLY MIN | `Ŧ0` |
| IN PLAY | `Ŧ81` |
| UPSIDE LEFT | **`Ŧ16.14`** |

- [ ] All four values match exactly.
- [ ] **`Ŧ16.14` fits cleanly — no clipping, no wrapping, no ellipsis.**
- [ ] All four cells remain aligned on one baseline; the taller value does not push its
      neighbours out of line.
- [ ] The `UPSIDE LEFT` label below it is unchanged and still fits on its own line.

> **Why this is the priority item.** `Ŧ16.14` is the **only value in the entire package
> that renders with decimal places** — every other strip cell drops a trailing `.00`
> (`Ŧ94`, `Ŧ0`, `Ŧ81`). It is six glyphs where the previous value (`Ŧ57`) was three, in a
> cell roughly 91px wide with ~83px of content, at the larger `.sumvalue` type. This is a
> genuine width check, not a formality.

## 2 · Account top strip

Open **Account + Gear v25**. The four cells must read:

| Cell | Expected |
|---|---|
| WALLET | `Ŧ94` |
| WEEKLY MIN | `Ŧ0` |
| IN PLAY | `Ŧ81` |
| FANTASYSTAKES SCORE | `+Ŧ65` |

- [ ] All four values match exactly.
- [ ] **`FANTASYSTAKES SCORE` still wraps to two lines without clipping.** This label was
      the tightest case in the prior certification (`min-height` was raised 16px → 20px to
      fit two 8px lines at 18.4px). Nothing about it changed here, but the neighbouring
      values did, so confirm no wrapping regression.
- [ ] Values stay on one baseline across all four cells.

## 3 · Ledger

Open **Account + Gear v25** → **MY LEDGER**.

- [ ] **35 rows** (was 33 — the Reba and Loretta commitments are the additions).
- [ ] Newest-first chronology is readable: top row `Nov 15`, bottom row `Sep 03`, with no
      backwards jump anywhere.
- [ ] The running **WALLET** column ends at **`Ŧ94`** on the top row.
- [ ] The foot line reads `35 transactions · newest first` and `WALLET Ŧ94`.
- [ ] Inspect the longest **newly added** description:
      `Pain vs Reba · issuer escrow retained under counter` (49 chars).
- [ ] Also inspect the **longest description overall**:
      `Season-opening Weekly FantasyStakes Competition allocation` (58 chars). This row
      predates this pass, but it is the true worst case for the TRANSACTION column — check
      it alongside the Reba row rather than assuming the new string is the widest.
- [ ] Neither pushes the MOVEMENT or WALLET columns out of the
      `64px / 1fr / 58px / 58px` grid.
- [ ] No horizontal overflow or clipping at phone width; the ledger scrolls inside its own
      pane and the phone frame does not scroll sideways.

## 4 · Single Team Prop Pool tile

Open **Action v24** → **PROP POOLS** tab → *Single Team: Punter Points*.

- [ ] Pain Sanders is shown as **entered** — status reads `ENTERED`, not `OPEN`.
- [ ] The `ENTERED` state fits its pill without clipping.
- [ ] **ENTERED** count reads **8** (was 7).
- [ ] **POT** reads **`Ŧ8`** (was `Ŧ7`).
- [ ] In the entry panel, the third cell label reads **`POT`**, not `IF YOU ENTER`.
- [ ] Footer copy reads *"Entry active · choose replacement pick"*.
- [ ] No layout regression in the tile or the pool sheet; the stat row stays on one line.
- [ ] The **Combined Teams** pool is unchanged: still `OPEN`, 6 entrants, pot `Ŧ6`.

## 5 · Widths

- [ ] **390px** — sweep all three artifacts. No horizontal scrollbar on the phone frame, no
      clipped text, no unexpected ellipsis.
- [ ] **360px** — repeat on **Action** only (the sole `@media(max-width:360px)` block).
      Pay particular attention to the top strip with `Ŧ16.14` in it, and to the four filter
      buttons, where `CHALLENGERS` is the tight one.
- [ ] Standings + Wrap Up needs a glance only: it is byte-identical to v7 outside its
      `<title>` and the inlined fixture, verified mechanically.

## 6 · Confirm the POR is unchanged

None of the following was touched in either pass. Any difference here is an unintended
regression — **report it, do not accept it.**

- [ ] Dark/gold palette unchanged: background, panel, gold accent, green, red.
- [ ] Bottom nav unchanged — same glyphs `≡ ▣ ⌁ ◎`, same order, one gold item per screen.
- [ ] Gear unchanged — button, overlay, all five cards, and the authority chips
      (`LOCKED FOR 2026` / `DERIVED`) in League Settings.
- [ ] `CLOSED` pills on LIVE/OVER no-wager cards unchanged.
- [ ] `PRE-GAME WIN%` on LIVE cards unchanged; pre-game cards still read plain `WIN%`
      (owner ruling 2026-08-28).
- [ ] No user-facing typography below the 8px floor. The suite proves no CSS declaration
      under 8px survives outside `.debug`; this is the rendered confirmation.
- [ ] Wrap Up highlight cards and symbol legend unchanged (owner ruling 2026-08-28:
      retained as accepted lock vocabulary).

---

## What is in this package

| File | Role |
|---|---|
| `fantasystakes_ACTION_uncluttered_full_prototype_v24_upside.html` | Action, subject of items 1, 4, 5 |
| `fantasystakes_ACCOUNT_GEAR_uncluttered_v25_upside.html` | Account + Gear, subject of items 2, 3 |
| `fantasystakes_STANDINGS_WRAPUP_deterministic_v8_upside.html` | Standings + Wrap Up, glance only |
| `FantasyStakes_Canonical_CrossTab_Fixture_v4.js` | Canonical fixture (reference copy — the HTML files inline it) |
| `FantasyStakes_Remediation_Reconciliation_v3.js` | 166-check suite; `node FantasyStakes_Remediation_Reconciliation_v3.js` |
| `FantasyStakes_Cross_Tab_Reconciliation_Phase6.md` / `.json` | Current reconciliation report and machine-readable results |
| `FantasyStakes_Residual_Lock_Blockers_v3.md` | Current residual list |
| `FantasyStakes_Finding_Disposition_Report_v2.md` | Disposition for **FSR-001 … FSR-023** |
| `FantasyStakes_Escrow_Before_After_v1.md` | The Ŧ138 → Ŧ94 escrow restatement, explained |

> **Note on the disposition report.** `FantasyStakes_Finding_Disposition_Report_v2.md`
> predates FSR-024 and covers FSR-001 through FSR-023 only. It is accurate for everything
> it covers and nothing in it was superseded by this pass. **FSR-024's disposition lives in
> `FantasyStakes_Cross_Tab_Reconciliation_Phase6.md` §1–§3 and
> `FantasyStakes_Residual_Lock_Blockers_v3.md` (R-13, closed).**

Both HTML artifacts and the Standings file load nothing external, and the bottom-nav and
gear controls resolve to each other inside this folder — unzip and open any of the three.

---

## Sign-off

| | |
|---|---|
| Certified by | |
| Date | |
| Browser / version | |
| Widths tested | 390px · 360px |
| Result | ☐ PASS ☐ PASS WITH FINDINGS ☐ FAIL |

**Findings (visual only — do not alter product logic):**

| # | Item | Screen | Description | Severity |
|---|---|---|---|---|
| | | | | |

A clean pass closes **R-1** in `FantasyStakes_Residual_Lock_Blockers_v3.md` and the package
is ready for final UI/system lock. The deferred fixture-coverage items (R-2 … R-5, R-12,
R-14) remain open and non-blocking.
