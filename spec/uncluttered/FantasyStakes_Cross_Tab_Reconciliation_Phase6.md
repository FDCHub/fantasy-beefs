# FantasyStakes — Cross-Tab Reconciliation, Phase 6

**Date:** 2026-08-28
**Supersedes:** Phase 5 (v23 / v7 / v24 against fixture v3)
**Subjects:** Action v24 · Standings + Wrap Up v8 · Account + Gear v25 · Fixture v4
**Result: 166 / 166 checks pass, 0 failures** (was 150 / 150)

Reproduce: `node spec/uncluttered/FantasyStakes_Remediation_Reconciliation_v3.js`
Machine-readable: `FantasyStakes_Cross_Tab_Reconciliation_Phase6.json`

**Scope: UPSIDE LEFT only.** No other economic value, lifecycle rule, probability, GE-603
behaviour, Ledger behaviour or visual treatment was touched.

---

## 1. The defect

The Action summary strip's fourth cell read a hard-coded `upsideLeft: 5700` carried in the
canonical fixture. It described nothing: it had survived the FSR-023 escrow restatement
untouched while Wallet moved Ŧ138 → Ŧ94 and escrow Ŧ36 → Ŧ80, and it had no derivation
behind it at all.

Definition applied: **remaining potential positive return from unresolved ACCEPTED
FantasyStakes wagers.**

## 2. Derivation by matchup

| Matchup | Lifecycle | Pain's side | Upside | Basis |
|---|---|---|---:|---|
| Hank Williams | ACCEPTED, unresolved (LIVE) | ANCHOR | **Ŧ7.40** | opponent's Derived stake on the frozen accepted proposal |
| Loretta Lynn | ACCEPTED, unresolved (LIVE) | ANCHOR | **Ŧ8.74** | opponent's Derived stake on the frozen accepted proposal |
| Dolly Parton | PENDING outgoing | — | Ŧ0 | no accepted counterparty — nothing left to win |
| Reba McEntire | COUNTER_PENDING | — | Ŧ0 | no accepted counterparty — nothing left to win |
| Prop Pool ticket | FUNDED | — | Ŧ0 | excluded — this is a Versus metric |
| | | | **Ŧ16.14** | |

Every other matchup contributes zero and is asserted to: Johnny (declined) and Patsy
(expired) are terminal; Waylon and George are incoming pending offers; Willie, Tammy and
Merle have no live proposal.

**Rendered:** `UPSIDE LEFT  Ŧ16.14` — read back from the DOM element `render()` wrote.

## 3. Rules encoded

```
accepted && unresolved && Pain is ANCHOR   -> upside = acceptedProposal.derived
accepted && unresolved && Pain is DERIVED  -> upside = acceptedProposal.anchor
accepted && game === "over"                -> 0   (outcome determined)
pending / counter-pending / declined /
expired / no proposal                      -> 0   (no accepted counterparty)
Prop Pool tickets                          -> excluded (Versus metric)
```

Two details worth recording:

- **The frozen proposal, not the live board.** Upside reads `acceptedProposal.derived`, not
  `m.derived`. Check F17.12 proves this by repricing the live board by Ŧ50 and asserting
  UPSIDE LEFT does not move.
- **A deliberately different "unresolved" test from escrow.** UPSIDE LEFT treats
  `game === "over"` as having no remaining potential and contributes zero, whereas escrow
  keeps an accepted wager committed until settlement. The two tests differ only for an
  accepted wager whose game is over, which does not exist in this fixture. The Derived-side
  and OVER branches are therefore unreachable from fixture data — check F17.9 drives the
  OVER branch directly rather than letting it pass vacuously.

## 4. Fixture v4

The only change is the deletion of the stale literal:

```diff
       qualifyingCommitmentsThisWeek:4100,
-      upsideLeft:5700,
+      // FSR-024: upsideLeft is deliberately absent. Remaining upside is a property of the
+      // accepted, unresolved proposals in the Action lifecycle...
       currentWeek:11
```

Plus the version bump and route targets. Wallet 9400, inPlay 8100, qualifying 4100,
unresolvedVersusEscrow 8000, the commitment schedule, settings, accounts, authority block
and all season data are **byte-identical** to v3.

Check F17.11 asserts `upsideLeft` is absent from `FS_CANON.action` *and* that no numeric
`upsideLeft` literal survives anywhere in the fixture source.

## 5. Standings v8 and Account v25

Fixture rebinding and title only, forced by the shared-canonical-source invariant (F1: all
three artifacts must inline the identical fixture). Both are **provably identical to v7 /
v24 outside the `<title>` and the inlined fixture block** — verified by mechanical
comparison, not by eye. No DOM, CSS or logic change.

## 6. Unchanged — asserted, not assumed

| Value | Phase 5 | Phase 6 |
|---|---:|---:|
| Wallet | Ŧ94 | **Ŧ94** |
| Weekly Min | Ŧ0 | **Ŧ0** |
| In Play | Ŧ81 | **Ŧ81** |
| Versus escrow | Ŧ80 | **Ŧ80** |
| Pool committed | Ŧ1 | **Ŧ1** |
| Qualifying commitments | Ŧ41 | **Ŧ41** |
| FantasyStakes Score | +Ŧ65 | **+Ŧ65** |
| Final Reconciliation | Ŧ285 | **Ŧ285** |

Checks F17.15 and F17.16 assert these explicitly inside the upside section, so a future
change to upside logic cannot quietly disturb them. Probability, moneyline and GE-603
economics are bit-identical between Action v23 and v24 across all eleven matchups and
eleven counter-board proposals.

## 7. Section results

| Section | Checks | Result |
|---|---:|---|
| 0 · Artifacts execute | 7 | PASS |
| F1 · Shared canonical source | 5 | PASS |
| F2 · Gear Season Allocation | 4 | PASS |
| F3 · Standard Prop Pool Entry | 4 | PASS |
| F4 · Current-week committed capital | 4 | PASS |
| F5 · Weekly Minimum | 3 | PASS |
| F6 · IN PLAY | 5 | PASS |
| F7 · Wallet | 4 | PASS |
| F8 · Skunk routing | 8 | PASS |
| F9 · Score chain | 7 | PASS |
| F10 · FSR-001 preserved | 8 | PASS |
| F11 · Integer-cent economics | 9 | PASS |
| F12 · Ledger chronology / presentation | 9 | PASS |
| F13 · AVAILABLE gating | 4 | PASS |
| F14 · Gear authority and season lock | 7 | PASS |
| F15 · Locked lifecycle battery | 14 | PASS |
| F16 · FSR-023 cross-surface committed capital | 30 | PASS |
| **F17 · FSR-024 UPSIDE LEFT** | **16** | **PASS** |
| N · Navigation contract | 16 | PASS |
| T · Type floor | 2 | PASS |
| **Total** | **166** | **PASS** |

## 8. Every Action summary value is now derived

| Cell | Source |
|---|---|
| WALLET | canonical, proven equal to the Ledger reconstruction (F7) |
| WEEKLY MIN | derived — `Resolver.commitmentTotals().weeklyMinRemaining` |
| IN PLAY | derived — `Resolver.commitmentTotals().inPlay` |
| UPSIDE LEFT | derived — `Resolver.commitmentTotals().upsideLeft` |

No stored literal remains behind any of the three lifecycle-dependent cells.

## 9. Evidence class

**SOURCE + RUNTIME**, unchanged. Artifact JavaScript executed, lifecycle driven, rendered
strip values read back from the DOM shim. **Not** a visual browser certification.
