# FantasyStakes — Production Mapping Carry-Forward

**Date:** 2026-08-28 · issued with the UI/System Final Lock
**Source:** `FantasyStakes_Residual_Lock_Blockers_v3.md`

---

## Purpose and standing

This list carries forward the **accepted non-blocking residuals** from the locked package
into the next phase. Every item below was reviewed and accepted at lock.

**None of these describes a defect in the locked UI/system contract.** The independent
Opus residual re-audit returned *READY TO LOCK WITH NON-BLOCKING RESIDUALS*, **0 blockers,
0 HIGH**. Nothing here reopens that verdict, and no new residual is introduced by this
document.

---

## 1 · `currentWeekCommitments` fixture schedule — production ledger adapter seam

**Carry-forward class:** adapter seam.

The canonical fixture publishes `currentWeekCommitments`: the current week's unresolved
commitments in posting order, each carrying `kind`, `lifecycle`, `role`, `cents`,
`qualifying`, `date` and `desc`. The Account Ledger builds its current-week postings from
this schedule rather than from hard-coded literals, and the reconciliation suite proves the
schedule against live Action lifecycle state (F16.25).

**This schedule is the seam where a production ledger adapter attaches.** It is the shape a
production commitment feed must satisfy.

> **Do not treat the fixture schedule as production authority.** It is a UI-coherence
> materialisation of Action lifecycle state, verified against it — not a system of record.
> In production the authority is the governed Ledger service; the schedule becomes a
> projection of it. The invariant to preserve is the *proof direction*: lifecycle state
> derives expected commitments, and the Ledger is checked against that derivation, never
> the reverse.

**Reference:** Residual v3 R-8 context, Phase 6 §4.

## 2 · Terminal escrow release with prior held escrow — production/integration test required

**Carry-forward class:** test coverage. *(Residual v3 · R-12)*

The commitment resolver correctly reports declined, expired and no-proposal matchups as
holding nothing, and check F16.24 asserts no Ledger escrow survives a terminal Action
state. But the fixture contains no historical **release** posting — those challenges'
escrow-at-issue and its release both predate the recorded canonical state, and no historical
movements were invented.

**Action for production:** add an explicit production/integration test covering a challenge
that escrows at issue and is then declined, cancelled or expired, asserting the release
posting exists, the Wallet is restored, and no escrow balance survives.

The resolver is architecturally capable of distinguishing held from released escrow today;
what is missing is the exercised Ledger path.

## 3 · Derived-side accepted incoming wager — production/integration test required

**Carry-forward class:** test coverage. *(Residual v3 · R-14, first branch)*

`Resolver.upsideCommitment()` handles the case where the current user holds the **Derived**
side of an accepted wager — upside is then the Anchor stake collected on a win. The current
fixture has the user as issuer on every accepted wager, so this branch never fires and is
**unverified by execution**.

The same gap affects committed capital: `versusCommitment()` computes a recipient's accepted
exposure as `acceptedProposal.derived`, also unexercised.

**Action for production:** add an explicit production/integration test in which the user
accepts an incoming challenge, asserting both the Derived-side escrow and the Derived-side
UPSIDE LEFT contribution. Pair with item 5 — the same fixture work closes several gaps.

## 4 · Accepted-but-game-over-before-settlement UPSIDE LEFT — production/integration test required

**Carry-forward class:** test coverage. *(Residual v3 · R-14 second branch, R-15)*

UPSIDE LEFT treats an accepted wager whose game is `OVER` as having no remaining potential
and contributing zero. Escrow keeps the same wager committed until settlement, so it still
counts toward IN PLAY.

Both readings are correct for their own metric — remaining *potential* ends when the outcome
is determined; committed *capital* is not released until settlement — and the difference is
deliberate and recorded (R-15). The two diverge only for an accepted wager whose game is
over, which this fixture does not contain. Check F17.9 drives the OVER branch directly
rather than letting it pass vacuously, but no fixture state reaches it naturally.

**Action for production:** add an explicit production/integration test for an accepted wager
between final whistle and settlement, asserting UPSIDE LEFT contributes zero while IN PLAY
still holds the commitment, and that settlement then releases the escrow.

## 5 · Reissue / Top-Off / correction fixture coverage — backlog only

**Carry-forward class:** production mapping / backlog coverage. *(Residual v3 · R-2, R-3)*

- **Reissue (R-3, FSR-009):** gate logic is correct and regression-tested in the refusal
  direction (F15.6), but no fixture state reaches a *successful* reissue.
- **Top-Off / refund / correction / championship settlement (R-2, FSR-008):** `topOffs`,
  `pointsChampionshipNet` and `fantasyStakesChampionshipNet` are all zero, so those Sheet
  lines and Ledger paths are structurally present but never exercised with a non-zero value.

Closing either changes canonical baselines — a non-zero Top-Off moves Final Reconciliation
off Ŧ285 — and therefore needs a deliberate rebaseline, which is why both were deferred
rather than rushed into a lock cycle.

> **No implication that the locked UI is defective.** These are coverage gaps in the demo
> fixture, not faults in the locked contract. The UI, Ledger and Sheet all handle these
> paths; the fixture simply does not drive them.

## 6 · Merle Haggard arithmetic plug — fixture-only cosmetic

**Carry-forward class:** fixture cosmetic. *(Residual v3 · R-4, FSR-017)*

The twelfth team absorbs the balancing remainder so each week's Matchup and Pool nets sum to
zero (`vals.push(-vals.reduce(...))`). Conservation is genuinely enforced and tested; one
team's weekly values are a by-product of that construction rather than modelled play.

Purely a fixture distribution artifact with no bearing on the locked contract. Related and
equally cosmetic: **R-5 (FSR-020)** — `skunkTeamIndex` cannot reach every team across ten
weeks, so two teams are never skunked. The Skunk mechanic itself is fully exercised and,
after FSR-016, correctly routed to the governed Skunk Pot.

## 7 · Route-target / version churn — packaging architecture concern

**Carry-forward class:** packaging architecture. *(Residual v3 · R-8)*

The canonical fixture carries a `routes` block naming artifact **filenames**. This is what
makes the persistent gear entry point and bottom nav resolve rather than sit dead, and it is
correct for a self-contained demo package. The cost: every re-version requires a fixture
edit purely to refresh route targets, and because all three artifacts must inline an
identical fixture, a fixture bump drags otherwise-unchanged artifacts into new versions.

That happened three consecutive times across the remediation passes, twice forcing
Standings and Account to be re-versioned with no semantic change at all. It became the
dominant churn in the package.

**Action for production:** consider decoupling route aliases from artifact versions —
either stable route keys resolved at load, or a small per-artifact binding outside the
canonical fixture. Not a defect, and deliberately not changed during a lock cycle.

## 8 · Debug-panel sub-8px typography — prototype-only

**Carry-forward class:** prototype hygiene. *(Residual v3 · R-10 context)*

The 8px user-facing type floor is enforced and machine-checked: no CSS declaration below
8px survives outside `.debug` (check T.1). The remaining sub-8px rules are the debug panel's
own (`.debugtitle`, `.debug select`, `.debug button` at 7px).

- **Not user-facing.** The panel is hidden unless `?debug=1` is present on the URL.
- **Prototype-only.** It exists to drive lifecycle states during testing.

**Action for production:** exclude or remove the debug panel from the production build. Its
typography then becomes moot rather than needing a fix.

Related and equally non-blocking: **R-10** proper — a trailing shared-typography block
re-declares several selectors, silently overriding earlier values. Harmless today (the
declarations were normalised so the source no longer misleads) but the two-competing-
declarations pattern will keep producing false-positive findings in future audits. Worth a
tidy-up outside a lock cycle.

## 9 · Owner decisions O-1 through O-4 — intentionally deferred

**Carry-forward class:** owner decision. *(Residual v3 · R-9)*

Recorded exactly as they stand:

| Ref | Decision | Status |
|---|---|---|
| **O-1** | final user-facing term `FIXED` vs `LOCKED` | **INTENTIONALLY DEFERRED** |
| **O-2** | optional Versus / Yahoo matchup terminology refinement | **INTENTIONALLY DEFERRED** |
| **O-3** | final terminal DECLINED / EXPIRED pill treatment | **INTENTIONALLY DEFERRED** |
| **O-4** | documentation-cascade timing | **INTENTIONALLY DEFERRED** |

These are deferred owner decisions, **not defects and not blockers**. No remediation pass
touched them. FSR-006 specifically introduced a separate neutral `CLOSED` state rather than
altering the terminal DECLINED / EXPIRED pills, precisely to avoid pre-empting O-3.

---

## Summary

| Item | Class | Action owner |
|---|---|---|
| 1 · `currentWeekCommitments` schedule | Adapter seam | Production mapping |
| 2 · Terminal escrow release | Test coverage | Production / integration |
| 3 · Derived-side accepted wager | Test coverage | Production / integration |
| 4 · Accepted-but-game-over upside | Test coverage | Production / integration |
| 5 · Reissue / Top-Off / correction | Backlog coverage | Fixture / backlog |
| 6 · Merle arithmetic plug (+ R-5 skunk spread) | Fixture cosmetic | Fixture / backlog |
| 7 · Route-target / version churn | Packaging architecture | Production mapping |
| 8 · Debug-panel typography (+ R-10 CSS tidy) | Prototype hygiene | Production build |
| 9 · O-1 … O-4 | Owner decision | Owner |

Also carried, informational only: **R-11** — Standings and Wrap Up display whole-token
integers rather than cents, which is correct today because no fractional value reaches
those surfaces; if that changes they need the same integer-cent treatment as Action.

**No new residuals are introduced by this document.**
