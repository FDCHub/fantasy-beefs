# FantasyStakes — UI / System Final Lock Summary

## LOCK STATUS: **LOCKED**

**Lock date:** 2026-08-28

---

## Certifications

| Certification | Result |
|---|---|
| Independent Opus residual re-audit | **READY TO LOCK WITH NON-BLOCKING RESIDUALS** |
| Deterministic / runtime reconciliation | **166 / 166 PASS**, 0 failures |
| Browser certification | **PASS** at 390px and 360px |

**Blockers: 0 · HIGH findings: 0**

The browser certification report and the Opus residual re-audit report are external
certification artifacts supplied separately; they are not held in this repository and were
not reconstructed here.

## Final canonical values

| | |
|---|---:|
| Wallet | **Ŧ94** |
| Weekly Min | **Ŧ0** |
| In Play | **Ŧ81** |
| Upside Left | **Ŧ16.14** |
| FantasyStakes Score | **+Ŧ65** |
| Final Reconciliation | **Ŧ285** |

## Locked artifact versions

| Artifact | Version | SHA-256 (short) |
|---|---|---|
| Canonical cross-tab fixture | **v4** | `9e23be45` |
| Action | **v24** | `61ec84be` |
| Standings + Wrap Up | **v8** | `fd155825` |
| Account + Gear | **v25** | `c1ea6076` |
| Reconciliation harness | **v3** | `afe04a76` |

Full hashes and the complete eleven-file locked set are in
`FantasyStakes_UI_System_Final_Lock_Manifest_2026-08-28.md`.

## Closed at lock

- **FSR-001** — probability derived from projected margin. CLOSED.
- **FSR-023** — cross-surface committed capital. CLOSED.
- **FSR-024** — UPSIDE LEFT derived from accepted wagers. CLOSED.
- Owner rulings: `PRE-GAME WIN%` on LIVE cards only; Wrap Up highlight vocabulary retained
  as accepted lock vocabulary.

## Remaining residuals — explicitly non-blocking

**Eleven** open, all non-blocking production-mapping or fixture-coverage items. None
describes a defect in the locked UI/system contract.

- Fixture / test coverage: R-2, R-3, R-4, R-5, R-12, R-14
- Owner input open: R-8, R-9 *(O-1 … O-4, intentionally deferred, not blockers)*
- Noted, no action: R-10, R-11, R-15

Carried forward in `FantasyStakes_Production_Mapping_Carry_Forward_2026-08-28.md`.

## Scope of this lock

This lock governs the **UI/system contract for the next demo / production mapping phase** —
the canonical UI contract, the cross-surface deterministic identities, the governed
economics and lifecycle behaviour, and the certified visual POR.

The canonical fixture is a UI-coherence source of truth only, never production authority.

## Next phase

**Production mapping and/or deterministic demo fork.**

Both inherit this contract. Production Yahoo / BALLDONTLIE adapters and the production
Ledger service replace fixture sources behind the same resolver boundary without changing
UI contracts. The four production/integration tests named in the carry-forward list
(terminal escrow release, Derived-side accepted wager, accepted-but-game-over upside, and
the reissue/Top-Off paths) should be written as that phase begins.
