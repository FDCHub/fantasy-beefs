# Sprint 8 · P4 Close Checklist

Findings that were **deliberately not solved in the package that found them**, and
must be closed before P4 can close. Each names the package that owns it.

A finding lands here when the correct fix is out of the discovering package's
scope — not when it is merely inconvenient. Anything on this list is a blocker
for P4 close, not a nice-to-have.

---

## MANDATORY · P4C-4 — `submit_pool_pick` wagering-actor ownership

**Status:** OPEN
**Owner:** S8-P4C-4 (Pool authorization repair + certification)
**Found by:** S8-P4C-1R, during the `assert_own_team()` caller inventory
**Restated by:** S8-P4C-2 (no Pool behaviour changed, as instructed)

`api/pool_routes.py:209` — `submit_pool_pick` still guards with the
commissioner-permissive `assert_own_team()`. A commissioner can therefore submit
a Pool pick **as another GM**.

**Why it was not fixed in P4C-1R or P4C-2.** The P4C-1R repair was scoped to
*wagering actor authority* — the paths that spend a team's Credits. Verified by
AST that `betting/pool_engine.submit_pool_pick` moves no money: no ledger post,
no escrow, no wallet mutation. So it is not a Credits path, and the ruling asked
for a repair narrow enough to leave commissioner administrative capability
intact. P4C-2 was then explicitly instructed not to change Pool behaviour.

**Why it still must be fixed.** It is a **game-integrity** defect rather than an
accounting one. Commissioner status must not confer another GM's Pool-pick
authority in the final MVP: a Pool pick decides who a GM is backing, and a
commissioner submitting one on someone's behalf changes that GM's competitive
position without their consent.

**What closing it requires**

- [ ] Classify `submit_pool_pick` as a **participant action**, not an
      administrative read.
- [ ] Guard it with strict ownership — `assert_wagering_team_owner()` or the
      Pool-domain equivalent, whichever the P4C-4 design settles on. Do not
      widen the wagering helper's name to cover Pools if the domains should stay
      separate; do not reuse the lenient helper.
- [ ] Prove a commissioner cannot submit a pick as another GM (403), and that
      **no pick row is written** on the refusal — the same "more than 403"
      standard P4C-1R held wagering to.
- [ ] Prove a commissioner CAN still submit their own team's pick.
- [ ] Re-audit every remaining `assert_own_team()` caller at that point. Two
      administrative reads are currently classified as legitimately
      commissioner-permissive — `faab_transactions` and `account_summary` — and
      that classification should be re-confirmed rather than inherited.

**Regression guard that already exists.** `test_s8_p4c1r_wagering_authority.py`
§1 pins the exact set of routes using each helper. Moving `submit_pool_pick` to
the strict guard will require updating that pinned set, which is intentional —
the set is meant to be changed deliberately and never drift.