# FantasyStakes — UI / System Final Lock Manifest

**Lock date: 2026-08-28**
**Lock status: LOCKED**
**Repository:** `fantasy-beefs-wired`, branch `postrc/yahoo-final-stats-recon`, HEAD `6246547`
**Package root:** `spec/uncluttered/`

---

## 1. Final locked candidate set

| # | Filename | Role |
|---|---|---|
| 1 | `FantasyStakes_Canonical_CrossTab_Fixture_v4.js` | Canonical cross-tab fixture |
| 2 | `fantasystakes_ACTION_uncluttered_full_prototype_v24_upside.html` | Action |
| 3 | `fantasystakes_STANDINGS_WRAPUP_deterministic_v8_upside.html` | Standings + Wrap Up |
| 4 | `fantasystakes_ACCOUNT_GEAR_uncluttered_v25_upside.html` | Account + Gear |
| 5 | `FantasyStakes_Remediation_Reconciliation_v3.js` | Deterministic reconciliation harness (166 checks) |
| 6 | `FantasyStakes_Cross_Tab_Reconciliation_Phase6.md` | Reconciliation report |
| 7 | `FantasyStakes_Cross_Tab_Reconciliation_Phase6.json` | Machine-readable results |
| 8 | `FantasyStakes_Residual_Lock_Blockers_v3.md` | Residual register |
| 9 | `FantasyStakes_Finding_Disposition_Report_v2.md` | Finding dispositions, FSR-001 … FSR-023 |
| 10 | `FantasyStakes_Escrow_Before_After_v1.md` | Escrow restatement explainer |
| 11 | `POST_UPSIDE_BROWSER_RECHECK_CHECKLIST.md` | Browser delta recheck checklist |

## 2. SHA-256 of every locked artifact

```
9e23be451b1719d9a0db412ae35d15b4d640d8a8b4dc9770bcc485d7597d478d  FantasyStakes_Canonical_CrossTab_Fixture_v4.js
61ec84be55728fb9b5b8ae7631f82693fad2961fbcad44a6c7420488d0c4e3b9  fantasystakes_ACTION_uncluttered_full_prototype_v24_upside.html
fd15582514ca3dc5097e6bfe32601cef8d83ed259772583b330f62d3042d326a  fantasystakes_STANDINGS_WRAPUP_deterministic_v8_upside.html
c1ea60762f82f953f0c7954f24cf706421d802982f46d22c9ba8078915e16f9d  fantasystakes_ACCOUNT_GEAR_uncluttered_v25_upside.html
afe04a762370a6cd511b92a3995f8dc19d4e3cc54626bd4aac3c74706d445cd1  FantasyStakes_Remediation_Reconciliation_v3.js
9b5fd2c9a8bfe0b9df6e497f95e2fa98f32898c6235630ab18ae9411f3024854  FantasyStakes_Cross_Tab_Reconciliation_Phase6.md
2d05b27d8443db01b61f4c3672d1df6a02576bba192ce5dfa4fe1cb9a4d70cf0  FantasyStakes_Cross_Tab_Reconciliation_Phase6.json
01c595001984d448db8886f36eba449e1047bc3eb2033efd2371f4f834e069f4  FantasyStakes_Residual_Lock_Blockers_v3.md
edecda4c7e61487729667aaf642baf0fd7eaa6cb7f5cd03f8c998b9482535be3  FantasyStakes_Finding_Disposition_Report_v2.md
d62eaef12f42833f06442d0ceedc3cd45a9a330312f4956fd3c6c0e2dd2d6659  FantasyStakes_Escrow_Before_After_v1.md
e658f5c98dbc1fd9958cdeb40fa8b3cd5606ec93a36616231e81e158165edd37  POST_UPSIDE_BROWSER_RECHECK_CHECKLIST.md
```

All three HTML artifacts inline a byte-identical copy of fixture v4 and each declares
`data-canonical-sha256="9e23be45…d478"`. The shared-canonical-source invariant is
machine-checked (F1.1 – F1.5).

## 3. Deterministic suite result

**166 / 166 PASS, 0 failures.** Exit code 0. Identical across repeated runs.

```
node spec/uncluttered/FantasyStakes_Remediation_Reconciliation_v3.js
```

| Section | Checks |
|---|---:|
| 0 · Artifacts execute | 7 |
| F1 · Shared canonical source | 5 |
| F2 · Gear Season Allocation | 4 |
| F3 · Standard Prop Pool Entry | 4 |
| F4 · Current-week committed capital | 4 |
| F5 · Weekly Minimum | 3 |
| F6 · IN PLAY | 5 |
| F7 · Wallet | 4 |
| F8 · Skunk routing | 8 |
| F9 · Score chain | 7 |
| F10 · FSR-001 probability model preserved | 8 |
| F11 · Integer-cent economics | 9 |
| F12 · Ledger chronology and presentation | 9 |
| F13 · AVAILABLE gating | 4 |
| F14 · Gear authority and season lock | 7 |
| F15 · Locked lifecycle regression battery | 14 |
| F16 · FSR-023 cross-surface committed capital | 30 |
| F17 · FSR-024 UPSIDE LEFT | 16 |
| N · Navigation contract | 16 |
| T · Type floor | 2 |
| **Total** | **166** |

Evidence class: **SOURCE + RUNTIME** — artifact JavaScript executed under a DOM shim,
lifecycle functions driven, rendered strip values read back from the elements `render()`
wrote.

## 4. Browser certification result

**PASS**, at 390px and 360px.

Scope: the post-UPSIDE-LEFT delta recheck defined in
`POST_UPSIDE_BROWSER_RECHECK_CHECKLIST.md` — Action and Account top strips, the 35-row
ledger, the Single Team Prop Pool tile's entered state, both widths, and confirmation the
POR is unchanged. The prior full visual certification remains authoritative for untouched
surfaces.

> **External certification artifact.** The browser certification report itself is **not
> present in this repository** and was **not** reproduced or reconstructed here. It is an
> external certification artifact supplied separately. This manifest records its
> disposition as accepted; it does not restate its contents.

## 5. Independent Opus residual re-audit result

**READY TO LOCK WITH NON-BLOCKING RESIDUALS**

- **Blockers: 0**
- **HIGH findings: 0**

> **External certification artifact.** The Opus residual re-audit report is **not present
> in this repository** and was **not** reproduced or reconstructed here. It is an external
> certification artifact supplied separately. This manifest records its verdict as
> accepted; it does not restate its contents.

## 6. Final canonical economic state

| Value | Locked |
|---|---:|
| **Wallet** | **Ŧ94** |
| **Weekly Min** | **Ŧ0** |
| **In Play** | **Ŧ81** |
| **Upside Left** | **Ŧ16.14** |
| **FantasyStakes Score** | **+Ŧ65** |
| **Final Reconciliation** | **Ŧ285** |

Supporting decomposition, all machine-verified:

| Component | Locked |
|---|---:|
| Unresolved Versus escrow | Ŧ80.00 |
| Unresolved Prop Pool commitment | Ŧ1.00 |
| Weekly Minimum qualifying commitments | Ŧ41.00 |
| Weekly Minimum setting | Ŧ10.00 |
| Season Allocation (Ŧ140 + Ŧ80) | Ŧ220.00 |
| Remaining weekly reserve | Ŧ30.00 |
| Championship reserve | Ŧ80.00 |
| Skunk Pot *(outside GM holdings, LED-346)* | Ŧ10.00 |
| **Total GM holdings** | **Ŧ285.00** |

`IN PLAY` (Ŧ81) and `Weekly Minimum qualifying commitments` (Ŧ41) are deliberately
different quantities. Every Action summary value except Wallet is derived from lifecycle
state; no stored literal remains behind WEEKLY MIN, IN PLAY or UPSIDE LEFT.

## 7. FSR-001 — **CLOSED**

Probability / projection coherence. `p = Φ((painProj − oppProj) / σ)` under the single
model `FS_DEMO_MARGIN_NORMAL_V1`, σ = 20.0. Fixed outside this repo in Action v21, carried
through unchanged across v22, v23 and v24 — probability, moneyline, counter-board `p` and
GE-603 economics are bit-identical at every version step. Re-proven at lock by checks
F10.1 – F10.8.

## 8. FSR-023 — **CLOSED**

Cross-surface committed capital. The Action lifecycle held four live Versus commitments
plus a funded Pool ticket while the Ledger recorded two, one mis-stated. Committed capital
is now derived from lifecycle state on both surfaces, IN PLAY and Weekly Minimum
qualification are computed as separate quantities, and the Ledger builds current-week
postings from the canonical commitment schedule. Wallet restated Ŧ138 → Ŧ94, IN PLAY
Ŧ37 → Ŧ81, total holdings conserved at Ŧ285. Verified by checks F16.1 – F16.30.

## 9. FSR-024 — **CLOSED**

UPSIDE LEFT. The stale `upsideLeft: 5700` literal is deleted from the canonical fixture,
not corrected. The value is derived from accepted, unresolved proposals — Hank Ŧ7.40 +
Loretta Ŧ8.74 = **Ŧ16.14** — read from the frozen accepted proposal rather than the live
board. Verified by checks F17.1 – F17.16.

## 10. Accepted owner rulings

Both ruled 2026-08-28 and implemented as ruled:

1. **`PRE-GAME WIN%` appears on LIVE cards only.** Pre-game cards retain plain `WIN%`. No
   live win-probability model exists or is implied.
2. **The current Wrap Up highlight vocabulary is retained as accepted lock vocabulary.**
   Card eyebrows (`BOLDEST WEEK`, `BOLDEST MATCHUP MOVE`, `BOLDEST POOL CALL`,
   `COSTLIEST BLUNDER`, `BIGGEST STEP BACK`) and the symbol legend map 1:1 through
   `▲ □ ◇ ‡ ▼`. The Standings audit publishes the eyebrow list under
   `highlightVocabulary`, so drift from the accepted vocabulary is detectable without a
   visual pass.

Neither ruling required a code change; both matched what had shipped.

## 11. Owner decisions O-1 through O-4 — intentionally unresolved, NOT blockers

The following remain **intentionally unresolved deferred owner decisions**. They are
**not** defects, **not** blockers, and were untouched by every remediation pass:

- **O-1:** final user-facing term `FIXED` vs `LOCKED`
- **O-2:** optional Versus / Yahoo matchup terminology refinement
- **O-3:** final terminal DECLINED / EXPIRED pill treatment
- **O-4:** documentation-cascade timing

FSR-006 deliberately introduced a separate neutral `CLOSED` state rather than altering the
terminal DECLINED / EXPIRED pills, specifically to avoid pre-empting O-3.

## 12. Remaining residuals — non-blocking

All remaining residuals are **non-blocking production-mapping and fixture-coverage items**.
None describes a defect in the locked UI/system contract. **Eleven** remain open, recorded
in `FantasyStakes_Residual_Lock_Blockers_v3.md` and carried forward in
`FantasyStakes_Production_Mapping_Carry_Forward_2026-08-28.md`:

| Class | Items |
|---|---|
| Fixture / test coverage | R-2, R-3, R-4, R-5, R-12, R-14 |
| Owner input open | R-8, R-9 *(O-1 … O-4)* |
| Noted, no action | R-10, R-11, R-15 |

Closed at lock: **R-1** (browser certification — PASS), **R-6** and **R-7** (owner rulings),
**R-13** (UPSIDE LEFT staleness, closed by FSR-024).

## 13. Scope of this lock

**This lock governs the UI/system contract for the next demo / production mapping phase.**

It fixes the canonical UI contract, the cross-surface deterministic identities, the
governed economics and lifecycle behaviour, and the visual POR as certified. Production
Yahoo / BALLDONTLIE adapter integration, the production Ledger service, and any deterministic
demo fork all inherit this contract and must not silently diverge from it.

The canonical cross-tab fixture is a **UI-coherence source of truth only**. It is not
production authority; production services replace fixture sources behind the same resolver
boundary without changing UI contracts.

## 14. Lock date

**2026-08-28.**

---

## Provenance

| Pass | Findings | Artifacts produced |
|---|---|---|
| Residual remediation | FSR-002 … FSR-019 | Action v22 · Standings v6 · Account v23 · Fixture v2 · 120/120 |
| Escrow reconciliation | FSR-023 | Action v23 · Standings v7 · Account v24 · Fixture v3 · 150/150 |
| Upside derivation | FSR-024 | Action v24 · Standings v8 · Account v25 · Fixture v4 · 166/166 |

Every superseded artifact remains on disk, unmodified, with its own passing suite: the v1
harness still returns 120/120 against v22/v6/v23 and the v2 harness still returns 150/150
against v23/v7/v24.

**No product file was modified during the creation of this manifest.**
