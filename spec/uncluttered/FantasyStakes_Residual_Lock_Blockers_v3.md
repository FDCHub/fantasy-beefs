# FantasyStakes — Residual List Before Final UI/System Lock (v3)

**Date:** 2026-08-28 · after the FSR-024 UPSIDE LEFT pass
**Supersedes:** `FantasyStakes_Residual_Lock_Blockers_v2.md` (unmodified on disk)
**Candidates:** Action v24 · Standings + Wrap Up v8 · Account + Gear v25 · Fixture v4

---

## Blocking

**None.** Deterministic reconciliation is 166/166.

---

## Outstanding before lock

### R-1 · Visual browser certification — **one cell added to the recheck**

The Phase 5 recheck list still stands in full. This pass adds exactly one changed value and
nothing else:

| Screen | Cell | Was | Now |
|---|---|---:|---:|
| Action strip | UPSIDE LEFT | Ŧ57 | **Ŧ16.14** |

**This is the only value in the package that renders with decimal places.** Every other
strip cell drops a trailing `.00` (`Ŧ94`, `Ŧ0`, `Ŧ81`), so `Ŧ16.14` is six glyphs against a
previous three. The strip cell is ~91px wide with ~83px of content, and `.sumvalue` type is
larger than the 8px labels, so this is the one place in the pass where a width check is
genuinely needed rather than a formality.

Carry over unchanged from v2: the four Phase-5 strip values (WALLET Ŧ94, IN PLAY Ŧ81 on
both screens), the two added ledger rows with the long *"issuer escrow retained under
counter"* description, and the Prop Pool tile's entered state.

**Not affected, do not re-test:** Gear authority chips, `CLOSED` pill, `PRE-GAME WIN%`,
focus rings, bottom nav, type floor, dark/gold POR, Standings and Account layout (both are
provably identical outside title and fixture).

---

## Deferred, non-blocking — fixture and coverage

### R-2 · FSR-008 — no non-zero Top-Off / refund / correction / championship settlement
Unchanged.

### R-3 · FSR-009 — REISSUE success path unreachable
Unchanged.

### R-4 · FSR-017 — Merle Haggard is an arithmetic residual plug
Unchanged.

### R-5 · FSR-020 — two teams never skunked
Unchanged.

### R-12 · No terminal-state escrow **release** transactions exist
Unchanged from v2. The resolver distinguishes held from released escrow and check F16.24
asserts no Ledger escrow survives a terminal state, but the release path itself is
unexercised in the Ledger because those challenges' escrow and release both predate the
recorded history. Pair with R-3 — both need the same kind of fixture work.

### R-14 · Two UPSIDE LEFT branches are unreachable from fixture data — **NEW**
`Resolver.upsideCommitment()` handles two cases the current fixture cannot produce:

- **Pain on the Derived side of an accepted wager** (upside would be the Anchor stake). Pain
  is the issuer on every accepted wager in the fixture, so this branch never fires.
- **An accepted wager whose game is OVER** (contributes zero — outcome determined).

Both are implemented because the metric is meaningless without them, and check F17.9 drives
the OVER branch directly rather than letting it pass vacuously. The Derived-side branch is
**not** driven and is currently unverified by execution. Closing this needs a fixture where
Pain accepts an incoming challenge — which would also close R-3's neighbouring gap in
lifecycle coverage.

---

## Owner input — closed

### R-6 · FSR-022 Wrap Up vocabulary — CLOSED, ruled 2026-08-28: RETAIN
### R-7 · FSR-013 PRE-GAME WIN% scope — CLOSED, ruled 2026-08-28: LIVE ONLY
### R-13 · UPSIDE LEFT staleness — **CLOSED by this pass**
Definition supplied by the owner and implemented: remaining potential positive return from
unresolved accepted wagers, derived from lifecycle state. The stale Ŧ57 literal is deleted
from the fixture, not corrected. No Action summary value is a stored literal any more.

---

## Owner input — open

### R-8 · Navigation route targets are filenames
`routes` in fixture v4 now points at the v24 / v8 / v25 filenames. This is the **third**
consecutive pass in which a re-version forced a fixture edit purely to keep route targets
current, and the second in which a fixture bump forced two otherwise-unchanged artifacts
(Standings, Account) to be re-versioned solely to preserve the shared-source invariant.

That cost is now the dominant churn in this package. Worth a decision before the next pass:
either move `routes` out of the canonical fixture into a small per-artifact binding, or
switch to stable route keys resolved at load. Not a defect, and not something to change
during a lock cycle — but it will keep recurring.

### R-9 · O-1 … O-4 remain open
Unchanged and untouched.

---

## Noted — no action taken

### R-10 · Dead type declarations in the shared typography block
Unchanged.

### R-11 · Standings/Wrap Up economics are whole tokens, not cents
Unchanged. Standings v8 is byte-identical to v7 outside title and fixture.

### R-15 · UPSIDE LEFT and escrow use different "unresolved" tests — **NEW, intentional**
UPSIDE LEFT treats `game === "over"` as having no remaining potential (contributes zero).
Escrow keeps an accepted wager committed until settlement, so the same matchup would still
count toward IN PLAY. Both readings are correct for their own metric — remaining *potential*
ends when the outcome is determined; committed *capital* is not released until settlement.
They diverge only for an accepted wager whose game is over, which this fixture does not
contain. Recorded so the difference is a conscious decision rather than something a future
audit rediscovers as an inconsistency.

---

## Readiness

Ready for the Opus residual re-audit and a short visual recheck. R-1 is now scoped to: the
four Phase-5 strip values, the two new ledger rows, the Prop Pool tile's entered state, and
**the Ŧ16.14 UPSIDE LEFT cell — the one value in the package that renders with decimals.**
