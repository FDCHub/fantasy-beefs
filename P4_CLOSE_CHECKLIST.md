# Sprint 8 · P4 Close Checklist

Findings that were **deliberately not solved in the package that found them**, and
must be closed before P4 can close. Each names the package that owns it.

A finding lands here when the correct fix is out of the discovering package's
scope — not when it is merely inconvenient. Anything on this list is a blocker
for P4 close, not a nice-to-have.

---

## CLOSED · P4C-4 — `submit_pool_pick` wagering-actor ownership

**Status:** CLOSED — S8-P4C-4
**Owner:** S8-P4C-4 (Pool authorization repair + certification)
**Found by:** S8-P4C-1R, during the `assert_own_team()` caller inventory
**Restated by:** S8-P4C-2 (no Pool behaviour changed, as instructed)

**The defect, as found.** `api/pool_routes.py` — `submit_pool_pick` guarded
with the commissioner-permissive `assert_own_team()`, so a commissioner could
submit a Pool pick **as another GM**.

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

**How it was closed (S8-P4C-4)**

- [x] Classified as a **participant action** — a Pool pick is a competitive
      choice, not an administrative read.
- [x] Guarded with `assert_wagering_team_owner()`. The helper gained an
      `action` parameter so the refusal names what was refused; it moves no
      Credits, and telling a GM they may not "wager with its Credits" when they
      submitted a pick describes the wrong act.
- [x] Proved a commissioner cannot pick as another GM (403), with **no pick
      row, no participation change and an unchanged trial balance** — the
      "more than 403" standard, in the API suite and in a real browser.
- [x] Proved a commissioner CAN submit their own team's pick — refused, when
      refused at all, for a Pool reason and never an ownership one.
- [x] Re-audited the remaining `assert_own_team()` callers: `faab_transactions`
      and `account_summary` remain administrative reads and keep the lenient
      guard, re-confirmed rather than inherited.

**A second defect was found and fixed in the same pass.** `POST /pool/predict`
(`submit_worst_beat_prediction`) had **no ownership check at all** — any
authenticated GM could submit a prediction as any team in any league, which is
weaker than the commissioner-permissive defect this item was opened for. It is
now strictly owned. Worst Beat is retired and cannot be drawn, but the route is
mounted and reachable, and a retired feature is not a reason to leave an
effectively unauthenticated write on it.

**Regression guards.** `test_s8_p4c1r_wagering_authority.py` §1 pins the exact
set of routes using each helper, and `test_s8_p4c4_pool_certification.py` §1
asserts structurally that the lenient guard is no longer CALLED anywhere in the
Pool routes. Both must be changed deliberately for the set to move again.