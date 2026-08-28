# FantasyStakes — Finding Disposition Report v2 (FSR-001 … FSR-023)

**Date:** 2026-08-28
**Supersedes:** `FantasyStakes_Finding_Disposition_Report_v1.md` (which remains valid for
the certified v22 / v6 / v23 package and is unmodified on disk)
**Subjects:** Action v23 · Standings + Wrap Up v7 · Account + Gear v24 · Fixture v3

---

## Summary

| Disposition | Count | Findings |
|---|---:|---|
| FIXED | 15 | FSR-002, 003, 004, 005, 006, 007, 010, 011, 012, 013, 014, 015, 016, 018, **023** |
| VERIFIED ALREADY FIXED | 2 | FSR-001, FSR-019 |
| DEFERRED NON-BLOCKING | 4 | FSR-008, 009, 017, 020 |
| OWNER DECISION — CLOSED | 2 | FSR-013 scope, FSR-022 (both ruled 2026-08-28) |
| NOT APPLICABLE | 1 | FSR-021 (subsumed by FSR-002) |
| **Total** | **23** | |

**Blockers remaining: 0.**

FSR-001 through FSR-022 carry their Report v1 dispositions unchanged. This document records
the new finding and the two amendments the escrow pass forced.

---

## NEW BLOCKER

### FSR-023 — Action lifecycle commitments not represented in Account / Ledger — **FIXED**

**Defect.** The certified Action board showed five live commitments for Pain Sanders while
the Ledger recorded three, two of them wrong:

| Action lifecycle | Should hold | Ledger held |
|---|---:|---:|
| Hank Williams — accepted, Pain is issuer | Ŧ20 | Ŧ20 ✓ |
| Dolly Parton — **pending outgoing**, Pain is issuer | Ŧ20 | Ŧ16, described as *"accepted exposure"* |
| Reba McEntire — counter-pending, Pain is original issuer | Ŧ20 | **absent** |
| Loretta Lynn — accepted, Pain is issuer | Ŧ20 | **absent** |
| Funded Prop Pool ticket | Ŧ1 | Ŧ1 ✓ |

IN PLAY therefore read Ŧ37 against an actual Ŧ81 of committed capital, and Wallet read Ŧ138
against an actual Ŧ94.

**Second defect found while building the resolver.** Pain was absent from *both* pools'
`entryRecords`, so Action reported the Single Team pool as **not entered** while the Ledger
carried a funded Ŧ1 ticket for it. The same class of disagreement, on the pool side, and
not visible until committed capital was derived from Action's own state. Pain's entry is
now seeded with `pick: null` — the artifact's existing "entry active, choose a pick" state,
which keeps zero Pool preselection intact.

**Fix.**

1. **Derivation, not literals.** `Resolver.versusCommitment()` and
   `Resolver.poolCommitment()` in Action derive every commitment from lifecycle state.
   `Resolver.commitmentTotals()` returns `{versusEscrow, poolCommitted, inPlay, qualifying,
   weeklyMinRemaining}`. The Action strip renders WEEKLY MIN and IN PLAY from these, so the
   strip cannot drift from the board it sits above.

2. **Escrow-at-issue encoded explicitly.** The issuer's Anchor is escrowed at issue and
   held while the challenge is live; a counter creates a new immutable proposal and moves
   no money, so the **original** issuer Anchor stays held (Reba: Ŧ20 from
   `proposalHistory[0]`, *not* the Ŧ26 counter Anchor); acceptance converts held escrow to
   accepted exposure, still held until settlement; declined / expired / cancelled release
   it. A recipient commits nothing before acceptance.

3. **IN PLAY ≠ Weekly Minimum qualification.** Computed as separate quantities and asserted
   to be different. IN PLAY Ŧ81 is every held commitment; qualification Ŧ41 is accepted
   Versus plus funded Pool only. Pending (Dolly) and counter-pending (Reba) are committed
   capital that does not yet qualify. The previous release asserted these were equal — that
   assertion is removed and inverted.

4. **Ledger rebuilt from the schedule.** The three hard-coded current-week postings are
   replaced by a loop over `FS_CANON.currentWeekCommitments`, so a live commitment can no
   longer go unrepresented and a description cannot contradict its lifecycle. Descriptions
   now read *pending issuer escrow* / *issuer escrow retained under counter* / *accepted
   wager escrow* / *funded pool entry*.

5. **Architectural test.** The prior suite compared shared literals, which is exactly why it
   missed this. Section F16 (30 checks) derives expected escrow from Action lifecycle state
   and drives it through the canonical schedule, the Ledger, and both **rendered** strips —
   read back out of the DOM elements `render()` wrote.

**Result.** Wallet Ŧ94 · Weekly Min Ŧ0 · IN PLAY Ŧ81 · Score +Ŧ65 · Final Reconciliation
Ŧ285. GM holdings conserve to Ŧ285 — Ŧ44 moved from Wallet into escrow, nothing created.

**Preserved:** every lifecycle rule in the governing set — issuer Anchor escrow at issue,
no money movement on counter creation, original issuer remains the Anchor side, counter
creates a new immutable proposal, no re-counter, acceptance selects the frozen proposal,
terminal states release escrow, accepted wagers stay committed until settlement, Pool
tickets stay committed until governed settlement, no silent balance changes, integer cents
only.

**Evidence:** checks **F16.1 – F16.30**, plus all 120 prior checks re-run and passing.

---

## Amendments to prior dispositions

### FSR-005 — amended

Report v1 recorded IN PLAY as Ŧ37 with qualifying commitments equal to it. The *principle*
was right and is unchanged — a funded Prop Pool ticket is both qualifying weekly action and
committed capital, and is counted exactly once. Two things were wrong underneath it:

- the Versus component was incomplete (Ŧ36 against an actual Ŧ80), corrected by FSR-023;
- qualifying commitments were asserted **equal** to IN PLAY, which conflated two different
  governed quantities. FSR-023 separates them: IN PLAY Ŧ81, qualifying Ŧ41.

FSR-005 remains **FIXED**; its numbers are superseded by FSR-023.

### FSR-013 — **OWNER DECISION CLOSED, ruled 2026-08-28**

Keep `PRE-GAME WIN%` on LIVE cards only; pre-game cards remain `WIN%`. Matches what
shipped; no code change was made under this ruling.

### FSR-022 — **OWNER DECISION CLOSED, ruled 2026-08-28**

Retain the Wrap Up highlight vocabulary and record it as accepted lock vocabulary. No code
change was made under this ruling. The Standings audit publishes the eyebrow list under
`highlightVocabulary`, so drift from the accepted vocabulary is detectable without a visual
pass.

---

## Unchanged dispositions

FSR-001 (verified already fixed, re-proven 8/8), FSR-002, 003, 004, 006, 007, 010, 011,
012, 014, 015, 016, 018 (fixed), FSR-019 (normalised), FSR-021 (not applicable, subsumed),
FSR-008 / 009 / 017 / 020 (deferred non-blocking fixture coverage).

See `FantasyStakes_Finding_Disposition_Report_v1.md` for the full text of each; none was
touched by this pass and all remain machine-verified in the 150-check suite.

## Deferred owner decisions — still untouched

O-1 FIXED vs LOCKED · O-2 Versus/Yahoo terminology · O-3 terminal DECLINED/EXPIRED pill
treatment · O-4 documentation cascade timing.
