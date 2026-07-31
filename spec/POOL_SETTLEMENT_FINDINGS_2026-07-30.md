# Pool Settlement — Money-Path Findings, 2026-07-30

**Status:** Recorded, not fixed. No code change authorized by this document.
**Scope:** Two defects in `betting/pool_engine.settle_pool`, both found during Weekly Pool Rotation recon.
**Product authority:** `spec/SPEC_Pool_Catalog_Rotation_POR_Rev1_0.md`

---

## Why this is a standalone artifact

Findings Register authority is currently unsettled. `Findings_Register_v16.md` and `Findings_Register_v17.md` both exist in the project panel, a delta dated 2026-07-30 remains unmerged, and no ruling names which version governs.

Rather than append to a register whose authority is ambiguous, these two findings are recorded here. **Fold them into the register once its authority is settled.** Do not treat this file as a permanent home.

Line references are evidence dated 2026-07-30. Re-grep before implementing.

---

## FR-POOL-1 — Biggest Winner empty result reported as distributed

**File / function:** `betting/pool_engine.py` · `settle_pool` · evaluator `_biggest_winner` (~:419–446), accounting at ~:782

**Current behavior**

`_biggest_winner` returns every team tied at the maximum wins:

```python
[(tid, float(w)) for tid, w in wins_map.items() if w == max_wins]
```

When no matchups produce a result the list is empty. `_split_even([], ...)` then returns `{}`, so no `_credit` call fires and no ledger posting occurs. The Biggest Winner pot is never paid.

`bw_share_cents` is nonetheless added into `total_distributed_cents` at approximately line 782.

**Economic risk**

The money stays in `pool:{league_id}`. The ledger is not corrupted — nothing was posted, so conservation holds and trial balance remains zero. **The defect is in reporting, not in the ledger.**

`PoolSettlementResult` reports a distribution that did not happen. Any surface consuming that figure — settlement report, feed, commissioner reconciliation — states that money moved when it did not. This is the same family as FR-8.7-LOG-5 and LOG-7: the ledger is right and a derived surface is wrong.

There is a second-order risk. The pot balance is not swept and not carried, so the cents are stranded in `pool:{league_id}` with no lineage record. A later week's reconciliation guard at ~:562–595 computes against expected balances and may or may not surface the discrepancy. That interaction is **not investigated**.

**Minimum reproduction**

A league/week where the Biggest Winner evaluator returns an empty set — no `Matchup` rows for the week, or no matchup with a determinable result — with a funded pot. Assert `total_distributed_cents` against actual `wager`-door postings rather than against the reported figure.

The fixture must produce a **discriminating** value: a case where reported and actual distribution differ. A fixture where the pot happens to be zero proves nothing.

**Why separate from rotation**

Rotation changes which definitions run and how the pot is divided. It does not change what an evaluator does with an empty result set. This defect exists at three pots today and would exist at four, or at ninety-four. Fixing it inside the rotation work would fuse an accounting correction with a structural change, and the two fail for different reasons.

**Recommended disposition**

Separate fix after review. Two candidate treatments, not yet chosen:

1. Exclude unpaid shares from `total_distributed_cents` and route the unpaid pot through the governed zero-claim rule — sweep or carry, per POR §6.
2. Fail closed on an empty evaluator result and refuse to settle the week, on the grounds that an empty result at a pot with funded entries indicates missing upstream data rather than a legitimate outcome.

Option 2 interacts with POR §6's zero-eligible-claims rule and needs a product read before it is chosen. **Money path — Opus math review gate on whichever is selected.**

---

## FR-POOL-2 — Special Teams empty result raises instead of failing closed

**File / function:** `betting/pool_engine.py` · `settle_pool` · Special Teams branch (~:753–775), `max()` call at ~:757

**Current behavior**

```python
max_st = max(sc for _, sc in st_scores)
```

No empty guard. When `st_scores` is empty, Python raises `ValueError: max() arg is an empty sequence`.

**Economic risk**

Lower than FR-POOL-1 in one respect and higher in another.

Lower, because the raise aborts the transaction. Whatever postings the settlement had already staged roll back, so no partial payout survives and conservation holds.

Higher, because the failure mode is an **unhandled generic exception**, not a governed refusal. It surfaces as a `ValueError` indistinguishable from any other, carries no domain message, names no cause, and is not routed through the fail-closed discipline the rest of the settlement path uses. An operator sees a stack trace, not a reason. Retry produces the same trace.

The week cannot settle until upstream data changes, and nothing in the error says so.

**Minimum reproduction**

A league/week reaching the Special Teams branch with an empty `st_scores` — no team with a computable special-teams score. Assert that settlement raises a **named domain error** identifying the empty result set, and that the message is distinguishable from the general `ValueError` surface.

Asserting only that it raises is non-discriminating: the current code raises too. The test must assert on the message.

**Why separate from rotation**

Same reasoning as FR-POOL-1. This is an evaluator-level guard, not a slate-level concern. Under the POR's two-family architecture the guard belongs to `RANK_EXTREMUM` generally, not to Special Teams specifically — which is an argument for fixing it as part of the evaluator framework rather than patching one branch.

**Recommended disposition**

Separate fix after review.

The narrow fix is an empty guard on the Special Teams branch with a named domain error. The better fix is a single empty-result rule inside the `RANK_EXTREMUM` evaluator specified in the POR, applied uniformly to all 73 definitions in that family.

**These two are the same question.** FR-POOL-1 is an empty result set treated as a silent no-op; FR-POOL-2 is an empty result set treated as a crash. Neither is a governed outcome. Whatever rule is chosen should apply to both, and the POR's zero-eligible-claims language in §6 is where that rule belongs.

Money path — Opus math review gate.

---

## Summary

| Finding | Location | Ledger correct | Failure mode | Gate |
|---|---|---|---|---|
| FR-POOL-1 | `_biggest_winner` / accounting ~:782 | yes | silent over-report | Opus |
| FR-POOL-2 | Special Teams branch ~:757 | yes | ungoverned raise | Opus |

Neither corrupts the ledger. Both concern what happens when an evaluator returns nothing, and neither answer is governed today.

**No fix is authorized by this document.** Both require review, a product read on the zero-result rule, and Opus math clearance before any code change.
