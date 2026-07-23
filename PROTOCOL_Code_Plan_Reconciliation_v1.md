# Code-Plan Reconciliation Audit Protocol — Fantasy Beefs

**Purpose:** Confirm every piece of deployed code matches current, ruled decisions — not what an earlier design said, not what a spec assumed, what's actually true today. This is a different failure mode than the Math Review Protocol (checks one spec's arithmetic) and the Plan Audit Protocol (checks the Master Plan document's internal consistency). This protocol exists because both of those passed everything they were asked to check, and a real contradiction still shipped: `collect_weekly_entries()` (a mandatory flat weekly pool ante, designed June 28 under a now-superseded model) and `shortfall_sweep.py` (the correct, current $10-weekly-minimum-across-any-bet-type mechanism, built later) have been coexisting, unreconciled, for weeks. Neither review process was ever asked "does this still match what we currently believe," because each only checked its own spec in isolation.

**Why this happened, stated plainly so it isn't repeated:** a design can be replaced in conversation without the code that implemented the old design ever being removed. Nobody's job, in either existing protocol, was to notice that two pieces of shipped code answer the same question two different, contradictory ways.

---

## Ground rules (same discipline as both existing protocols)

- **Findings only. No fixes, no rewrites, no code changes this pass.**
- **Four-part format per finding:** Location (file + line, or doc + section) / Plain English (what the code actually does vs. what current plan says) / Why it matters (what breaks, who's affected, is it money-path) / Correct approach (shape of the fix, not the fix itself).
- **Cite the actual code.** A finding that says "this doesn't match the plan" without quoting the specific function and the specific doc section it contradicts is not a usable finding.
- **Every finding needs two sources: the code as it exists right now, and the specific current doc/ruling it's being checked against.** Not memory of what was probably decided — the actual current canonical document.
- **Distinguish three outcomes per piece of code checked:** (a) matches current plan, no finding needed; (b) implements an old, superseded decision that was never removed; (c) was never speced at all — code exists with no corresponding decision anywhere.
- **Fraser reviews and rules on each finding individually**, same as every other review this project runs.

---

## Canonical documents to check code against

(Reviewer: treat this list as the current source of truth. If code contradicts something not on this list, flag it as "possibly superseded doc" rather than assuming the list is complete.)

- `FantasyBeefs_MasterPlan_BAB_Reconciled_v7.md` + the Percent Update chain through `2026-07-13_Session2`
- `FantasyBeefs_Findings_Register` through the `2026-07-13_Session2` update
- `FantasyBeefs_New_Thread_Handoff_v45.md`
- This session's playoff-policy rulings and the FR-6.1 catalog classification (not yet folded into the register — treat as current, pending fold-in)
- `L1_LEDGER_PRIMITIVE_MODULE_SPEC.md` and all certified FINDING_*_Rev*_FINAL specs currently in the project panel

---

## Batching plan — by subsystem, money-path first

Full repo: 129 files, ~31,000 lines. Too large for one pass without skimming — the exact failure mode this protocol exists to prevent. Run as separate, focused passes, in this order:

**Batch 1 — Economy & Wallet Foundation (highest risk, do first)**
`ledger/`, `wallet/`, `payments/`, `db/schema.py`, `betting/shortfall_sweep.py`, `betting/pool_engine.py`
*This is the batch that would have caught today's finding.* Explicitly check: does every mechanism claiming to enforce "the weekly minimum" or "pool participation" agree on what model it's implementing? List every function that debits a wallet unconditionally vs. only on opt-in, and cross-check each against the current ruling (opt-in, self-funded, no universal ante).

**Batch 2 — Betting Mechanics**
`beefs/beef_engine.py`, `betting/settlement_engine.py`, `betting/per_bet_lock.py`
Check bet_type coverage (does code match the current 3-vs-bet-type ruling, is `the_lineup` cleanly absent now, is `prop` cleanly retired, not just blocked-at-issuance-but-still-referenced-elsewhere). Check push/tie handling matches today's ruling (vs bets never roll over, refund on tie).

**Batch 3 — API & Routes**
`api/`
Cross-check every route against what the frontend (`tools/app.html`) actually calls, and against what the batch 1/2 findings say *should* be exposed. This is also where the "frontend wiring" gap from earlier sessions lives — confirm it's still accurately described as the critical path, not something quietly worked around.

**Batch 4 — Everything else**
`engine/`, `odds/`, `data/`, `connectors/`, `feed/`, `reports/`, `notifications/`, `admin/`, `auth/`, `scripts/`, `tools/`
Lower money-risk, but check for the same class of problem — dead code implementing retired ideas, orphaned functions with no current spec backing them.

---

## What NOT to do in this pass

- Do not fix anything found. Findings only.
- Do not assume the canonical-docs list above is complete or perfectly current — if something looks unaddressed, say so as its own finding rather than silently picking one interpretation.
- Do not re-review math already certified by a prior Opus Math Review pass — this protocol checks *whether the right things were even certified*, not whether the certified math is right (that's already been checked).

---

## How to use this

Clone the repo fresh into a sandbox. For each batch: read every file in scope, then check each function/mechanism against the canonical docs list. Produce numbered findings (`CPR-1`, `CPR-2`, ...) in the four-part format. Bring findings back to Fraser one batch at a time — don't run all four batches before any review, since Batch 1's findings may change what Batch 2 needs to check.
