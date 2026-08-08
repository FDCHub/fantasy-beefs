# FR-8.7-BUG-1 — Empty-Week Stranding Fix — MODULE_SPEC (Opus-ready)

**Status:** Opus review package. Money-path. Issues-only — no fix authorized until each finding is approved individually.
**Source basis:** verbatim `betting/settlement_engine.py` at HEAD `d60943a`, branch `remediation/foundation-phase-1`. Lines cited are read, not paraphrased.
**Reviewer instruction:** surface issues only, four-part format (Name / Issue Summary / Options / Recommendation & Reasoning). Do not write the fix. Fraser approves each finding before any code.

---

## Self-check (required before Opus): internal consistency

- The fix adds no ledger postings. It writes settlement-lifecycle state only (`week_settlements` row), never `wallet`, `escrow`, or any ledger account. There is no posting to sum to zero — this is a lifecycle transition, not an economic one. Stated explicitly so Opus does not look for a zero-sum posting that does not exist.
- The fix reuses an existing, in-transaction guarded UPDATE (746–780) rather than introducing a new one. No new SQL is proposed.
- The Phase-1 claim (351–360) is not moved, reworded, or reordered. Finding 5.9's serialization dependency on that claim is untouched.

---

## 1. The defect (verified)

**Current behavior, lines 497–511** (source text reproduced with line numbers prefixed and indentation normalized to document style; wording, operators, and f-string content are exact):

497 pending = (
498 db.query(Bet)
499 .join(Matchup)
500 .filter(
501 Matchup.league_id == league_id,
502 Matchup.week == week,
503 Bet.status == "pending",
504 )
505 .order_by(Bet.id)
506 .all()
507 )
508
509 if not pending:
510 return SettlementReport(week=week, total_bets=0, bets_won=0, bets_lost=0,
511 total_staked=0.0, total_payout=0.0)


This early return fires **after** the Phase-1 claim committed `status='CLAIMED'` at line 360 and **after** the Phase-2 lock was acquired at line 435. It executes no `UPDATE`, no `db.commit()`, no `db.rollback()`. Session teardown may release the open `FOR UPDATE` lock, but cannot undo the already-committed `CLAIMED` state.

**Consequence (verified against the conflict path at 386–418):** the row remains `status='CLAIMED'`, `settled=FALSE`, `recovery_token=NULL`. A subsequent plain `settle_week` on that week takes the Phase-1 conflict path, reads `CLAIMED` with `recovery_token IS None` at guard 4a (line 394), and raises the manual-recovery `ValueError` at 395. The empty week is **persistently stranded as CLAIMED** — recoverable only via authorized `recover_week` or manual repair, not settleable by ordinary means.

**Trigger surface (inferred):** any week reaching Phase-2 with zero pending bets — a week where every bet was voided, a week settled before any bets were placed, or a league-week with no action. This path is reachable in principle; whether it has occurred in production is not verified.

## 2. The proposed fix (for Opus to critique, not to implement)

Route the zero-pending case through the existing terminal-transition block (746–780) instead of the bare return at 510–511. Source text reproduced with line numbers prefixed and indentation normalized to document style; wording, operators, and f-string content are exact:

746 if claimant_type == "normal":
747 result = db.execute(
748 text("""
749 UPDATE week_settlements
750 SET status='COMPLETED', settled_at=:now, settled=TRUE, recovery_token=NULL
751 WHERE league_id=:league_id AND week=:week
752 AND status='CLAIMED' AND recovery_token IS NULL
753 """),
754 {"now": now, "league_id": league_id, "week": week},
755 )
756 else: # claimant_type == "recovery"
757 result = db.execute(
758 text("""
759 UPDATE week_settlements
760 SET status='COMPLETED', settled_at=:now, settled=TRUE, recovery_token=NULL
761 WHERE league_id=:league_id AND week=:week
762 AND status='CLAIMED' AND recovery_token=:presented_token
763 """),
764 {"now": now, "league_id": league_id, "week": week,
765 "presented_token": recovery_token},
766 )
767
768 if result.rowcount != 1:
769 # Fail closed — the claimant-specific WHERE matched no row (or, under the
770 # unique (league_id, week) constraint, could only ever be 0 or 1). Payouts
771 # are already STAGED in this session, so roll back (via _abort_phase2)
772 # before raising — nothing commits under a claimant/token mismatch. This
773 # is the most important rollback of the function.
774 _abort_phase2(
775 f"[settle_week] week={week} league_id={league_id}: COMPLETED flip affected "
776 f"{result.rowcount} row(s) (expected 1) for claimant_type={claimant_type!r} — "
777 f"refusing to commit payouts (fail-closed)."
778 )
779
780 db.commit()


**Why this block is valid for a zero-bet week (verified):** the SET clause is byte-identical across branches (750 == 760). The WHERE keys only on `(league_id, week) + status='CLAIMED' +` the token predicate — no dependency on pending bets existing. Every name it reads (`now`, `claimant_type`, `recovery_token`, `league_id`, `week`, `_abort_phase2`) is already bound before line 509. So the empty-week path can execute the same completion the normal path does, preserving the `rowcount != 1` fail-closed guard and the normal/recovery branching.

**The change in one sentence:** the empty-week case reaches the *same single* claimant-specific guarded completion the payout path reaches, then returns the empty report — rather than returning while leaving the row CLAIMED.

**Binding constraint on the fix shape (do not violate):** there must be exactly **one** implementation of the completion transition (the SQL of 746–766, the `rowcount != 1` abort of 768–778, and the commit at 780). The empty-week case and the payout case must both reach that single implementation. **Copying lines 746–780 into the empty-week branch is forbidden** — two copies of the lifecycle completion would drift the moment one branch's SQL is edited and the other is missed, a divergence on a money path that no test reliably catches. Acceptable shapes: (a) restructure control flow so the empty case falls through to the existing block instead of returning early, or (b) extract a narrowly-scoped helper (e.g. `_complete_week(claimant_type, recovery_token, now, league_id, week, db)`) holding the identical SQL and failure behavior, called from both the payout site and the empty-week site. The implementer chooses (a) or (b); the invariant is one completion path, not two.

**Explicitly rejected alternative:** a simplified unconditional `UPDATE ... SET status='COMPLETED'` in the empty-week branch. It would strand-proof the row but discard the claimant/token/`rowcount==1` controls, trading a stranding bug for a concurrent-completion hole. The fix must reach the guarded form, not a weakened one — and must reach the *shared* guarded form, not a duplicated one.

---

## Findings for Opus review

### MS-BUG1-1 — Does routing the empty-week case through 746–780 preserve the claimant/token invariant?

**Issue summary.** The normal-claimant branch's WHERE requires `recovery_token IS NULL` (752); the recovery branch requires `recovery_token=:presented_token` (762). The empty-week path can be reached by either a normal caller or a recovery caller (a recovery of a week that turns out empty). The fix must select the correct branch by `claimant_type`, exactly as the payout path does at 746/756. Question for review: is there any state in which the empty-week path reaches this block with a `claimant_type` that does not match the row's actual token state — producing a `rowcount==0` false abort on a week that legitimately has nothing to settle?

**Options.** (a) Reuse the full `if claimant_type == "normal" / else` branching unchanged. (b) Assume empty weeks are always normal-claimant and reuse only the normal branch. (c) Something Opus identifies.

**Recommendation & reasoning.** (a). The recon confirms `claimant_type` is already correctly bound before line 509 by the same Phase-1 logic that binds it for the payout path — a recovery caller reaching an empty week still holds `claimant_type='recovery'` and its token. Reusing the full branching means the empty-week completion is gated by the identical invariant as a normal completion; a mismatch aborts fail-closed rather than completing wrongly. (b) is rejected: it would false-abort a legitimate empty-week recovery. This is the finding most worth Opus's attention because it is the one place the reuse could be subtly wrong.

### MS-BUG1-2 — Is a `rowcount != 1` abort on an empty week correct, or should an empty week that finds no CLAIMED row behave differently?

**Issue summary.** If the empty-week path executes the guarded UPDATE and `rowcount != 1`, the current block calls `_abort_phase2`, which rolls back and raises (768–778). For the payout path this rollback protects staged payouts. For the empty-week path there are no staged payouts — nothing economic was done. Question: is raising the fail-closed `ValueError` the correct outcome when the guarded UPDATE affects no row, indicating that the locked row no longer matches the claimant/status/token state this same transaction previously revalidated?

**Options.** (a) Reuse `_abort_phase2` unchanged — a `rowcount != 1` on an empty week means the locked row no longer matches the state this transaction revalidated, and failing closed is correct. (b) Treat `rowcount==0` on an empty week as a benign no-op and return the empty report without raising. (c) Opus's call.

**Recommendation & reasoning.** (a). By the time this caller reaches the completion UPDATE it already holds the `FOR UPDATE` lock (acquired at 435) and has revalidated the row's claimant/status/token state under that lock. A `rowcount != 1` therefore does not indicate a concurrent completer — the lock precludes that — but an internal invariant failure: the locked row no longer matches what this same transaction just revalidated. Failing closed surfaces that anomaly rather than masking it, consistent with the rest of Phase-2's fail-closed posture. The idempotent "already completed" case is handled earlier, on the Phase-1 conflict path at 386, before this caller ever reaches Phase-2, so a `rowcount==0` here is genuinely unexpected, not the benign already-done case. This depends on the claimant-binding reading in MS-BUG1-1, so Opus should rule them together.

### MS-BUG1-5 — The fix must produce one completion path, not two. Which shape?

**Issue summary.** The completion transition (SQL 746–766, `rowcount != 1` abort 768–778, commit 780) must have exactly one implementation after this fix. If the empty-week branch gets its own copy of that block, the two copies drift the first time one is edited and the other is not — a silent money-path divergence. The fix must route both the payout case and the empty case through a single implementation. This is a binding constraint, restated here as a review target so Opus checks the chosen shape actually achieves single-sourcing without altering the SQL or failure behavior.

**Options.** (a) Control-flow restructure: replace the early return at 509–511 so the empty case falls through to the existing 746–780 block, guarded so the payout loop (513–736) is skipped when `pending` is empty. (b) Extract a narrowly-scoped helper holding the identical SQL and abort logic, called from both the payout completion site and the empty-week site. (c) Opus proposes a cleaner single-source shape.

**Recommendation & reasoning.** Weak preference for (b), the extracted helper, because it makes the single-sourcing explicit and self-documenting — one named function is the completion transition, and both callers demonstrably use it. (a) is lighter (no new function) but relies on fall-through control flow that a future edit could re-split, reintroducing the early-return shape. Either satisfies the invariant; Opus should confirm the chosen shape leaves the SQL byte-identical to 750/760 and the abort behavior identical to 768–778. The one unacceptable outcome is two copies.

### MS-BUG1-3 — Does the empty-week completion need `log_settlement_events`, or is skipping it correct?

**Issue summary.** The payout path calls `log_settlement_events(pending, db)` at 781 after commit. The empty-week path has an empty `pending`. If the fix routes through 746–780 and then returns, it does not reach 781. Question: should an empty week emit any settlement event, or is emitting nothing correct for a week with no bets?

**Options.** (a) Emit nothing — an empty week has no settlements to log. (b) Emit a "week completed, no action" event for feed/audit completeness. (c) Opus's call.

**Recommendation & reasoning.** (a). `log_settlement_events` takes `pending`, which is empty here; calling it with an empty list either no-ops or logs nothing meaningful. An empty week producing no feed event is defensible. This finding is raised only so the omission is a decision, not an oversight — and it intersects FR-8.7-LOG-1, which is separately reviewing that same call's failure handling. Note the intersection; do not fix it here.

### MS-BUG1-4 — Test dependency: the 6d empty-week assertion (spec §B-1) is blocked on this fix.

**Issue summary.** The frozen 6d spec's adjacent assertion B-1 asserts that an empty week reaches COMPLETED and retry-no-ops. That assertion cannot be written against current code — it tests the fixed behavior. This is a sequencing note, not a defect: FR-8.7-BUG-1 must be approved, built, and reviewed before B-1's test is written, or the test is written against code about to change.

**Options.** (a) Fix BUG-1, then write B-1 against fixed behavior. (b) Write B-1 first, run it locally to establish the expected failure, then implement BUG-1 and rerun green — do not commit or push the test while it is failing. (c) Opus's call.

**Recommendation & reasoning.** (b) is the cleaner shape and gives a local red-to-green proof of the fix, with the red state kept local and temporary — the failing test is never committed or pushed. (a) is simpler and matches how 6c was built. Either works; flagging so the order is chosen, not stumbled into.

---

## What Opus should explicitly confirm or reject

1. That routing the empty-week case through 746–780 introduces no path where a legitimate empty week false-aborts (MS-BUG1-1 + MS-BUG1-2 together).
2. That reusing the guarded UPDATE — not a simplified unconditional one — is the correct strength.
3. That the chosen fix shape produces **one** completion implementation, not two copies (MS-BUG1-5), with SQL and failure behavior byte-identical to the current 746–780.
4. That the Phase-1 claim and Finding 5.9's serialization are genuinely untouched by this change.
5. Any edge the issues above missed.

## What is out of scope for this review

- FR-8.7-LOG-1 (post-commit logging contract) — separate review.
- The 6d test implementation — frozen spec, not built.
- Any change to the payout path itself (677–736) — this fix touches only the empty-week branch.
