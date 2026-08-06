# B2 — Stripe Removal Addendum
## Revision 1 — addendum to SPEC_B2_Group2_Season_Allocation_Contract_v1.md

**Status:** Addendum of record. It adds; it rewrites nothing.
**Branch:** `b2/stripe-removal-season-allocation`
**Base:** `86e7402aefb2f83a77c361f37c879acaa00a0a94`
**Date:** 2026-08-05

---

## 1. Why this file exists

`SPEC_B2_Group2_Season_Allocation_Contract_v1.md` is silent on which production
sites may write a `reserve:{team_id}` ledger leg. That silence produced blocker
**B-1**: `test_championship_payout.py` Item 8 asserted that
`confirm_buyin_payment()` was the sole writer, and B2 introduced a second one
without recording the change.

The Door 1 reachability evidence then established that `confirm_buyin_payment()`
was **production-reachable** at that head — `POST /payments/buyin-confirm` was a
registered route gated only by `require_commissioner`, with no Stripe secret,
webhook signature or feature flag on the path, and the two funding paths could
not see each other. So B-1 was a live double-funding exposure, not a stale
assertion.

**This addendum does not amend the Group 2 contract.** That contract's five-state
model, retained result interface, gate surface and sealed evidence all stand
exactly as written. This file records what changed *after* it, and why.

---

## 2. Product of record

Stripe is out of the FantasyStakes MVP.

The MVP contains no production-reachable Stripe route, funding logic,
compatibility funding path, payment processing, connected-account logic, payout
logic, or real-money fallback or parallel path.

**Season allocation plus the internal Credits ledger is the sole MVP funding and
accounting model.**

Historical migrations, schema columns and evidence may remain where needed for
audit or history. They must not be production-reachable.

---

## 3. The superseded invariant, stated explicitly

**SUPERSEDED (Finding 5.2-1):** `confirm_buyin_payment()` is the only production
writer to `reserve:{team_id}`.

**IN FORCE (this addendum):** `activate_season_allocation()` is the sole
production writer of the season-opening wallet and championship-reserve funding
posting.

The superseded invariant is not deleted from the record. It was correct for the
Stripe-funded design and is retained here so that a future reader comparing
Finding 5.2 against the shipped code finds the divergence already explained
rather than discovering it as an unexplained contradiction.

### 3.1 — The guard protects the operation, not the string

The replacement regression guard does not grep for the literal account name. It
walks the AST of every production module, finds each call to `post()` /
`ledger_post()`, and flags any call whose leg list constructs a `reserve:{...}`
account — reporting the enclosing function.

This is deliberate and load-bearing. A text search can be defeated by
reformatting, and it trips on comments and docstrings that merely mention the
account. The structural check cannot be, and does not.

Implemented in `test_stripe_removal_regression.py` Item 3 and
`test_championship_payout.py` Item 8. Both assert the single site is
`economy/season_allocation.py`, inside `activate_season_allocation()`.

---

## 4. What was removed

**Deleted module:** `payments/stripe_connect.py` in full.

**Deregistered routes** — all previously registered on the live app:

| Route | What it did |
|---|---|
| `POST /payments/buyin-confirm` | Door 1 — the reachable double-funding path |
| `POST /payments/buyin-link/{team_id}` | Stripe Payment Link creation |
| `POST /payments/webhook` | Stripe webhook receiver |
| `GET /payments/connect-link/{team_id}` | connected-account onboarding |
| `GET /payments/payout-preview/{league_id}` | payout preview |
| `POST /payments/payout-execute` | payout execution |
| `GET /payments/buyin-status/{league_id}` | Stripe-mediated buy-in status |
| `POST /payments/setup-treasury` | buy-in amount + payout split |
| `GET /payments/treasury/{league_id}` | LeagueTreasury state (already retired) |
| `GET /payments/audit-log/{league_id}` | Stripe audit trail |

**Second funding rail removed.** `wallet/faab_wallet.py` carried an independent
Stripe path that the original removal plan did not enumerate:
`_create_stripe_link()`, the `stripe` SDK import, `STRIPE_SECRET_KEY`,
`MOCK_MODE`, and real-mode branches in both top-up creators. A top-up is now
recorded as a pending request that a commissioner confirms; no payment is taken
and no funds move at request time.

This aligns the code with `FantasyBeefs_BAB_TopOff_UIUX_Spec_2026-07-21.md`,
which already ruled that a top-off is a **BAB issuance event (internal
accounting)** and that "no real money moves through Fantasy Beefs" — expressly
contrasting it with buy-in confirmation, "which was cut because the app tracks no
payments."

**NOT built here.** That spec's item B6 requires an approved top-off to debit a
league-season **BAB issuance account** rather than `world`, and records that no
such account or door exists yet, and that approver identity and request↔credit
linkage are absent. Those keys remain unpinned. This addendum removes the
payment rail only; it does not invent the issuance ledger model. The
`FaabTransaction.wallet_from` marker was changed from `"stripe"` to
`"issuance"` — that column is descriptive metadata, not a ledger account, so the
change carries no accounting effect.

---

## 5. What was retained, and why

**Schema columns.** `BuyInRecord`, `LeagueTreasury`, `PayoutRecord`,
`StripeAuditLog`, `User.buy_in_paid` (DEBT-3), and the `FaabTransaction`
`stripe_*` columns all remain in `db/schema.py`. They hold historical rows.
Dropping them is a controlled post-MVP migration, not part of this package.

**Historical migrations.** `db/migrate_payments.py` and every migration
mentioning Stripe remain untouched. They are history, and none is
production-reachable.

**Enforcement flag.** `League.buyin_enforcement_active` keeps its historical
name. It is the season-allocation enforcement flag and has no payment meaning.
`set_buyin_enforcement_active` was relocated to
`auth/allocation_gate.set_allocation_enforcement_active`; its StripeAuditLog
write went with the deleted module. Renaming the column and the
`/payments/buyin-enforcement` route path is deferred.

---

## 6. Commissioner scope — unchanged, and still open

`require_commissioner` (`auth/jwt_auth.py:105`) tests `user.role` only. It takes
no `league_id`, `auth/jwt_auth.py` contains no `league_id` reference, and `User`
has no league column. **Commissioner authorization is global.**

Removing the Stripe routes did not create this and did not widen it — but it did
change the shape of the exposure: `POST /league/{league_id}/season-allocation`
is now the only registered money-moving commissioner route, and it remains
callable by any commissioner for any league.

Classified **REQUIRED — next package**, not a blocker for this one. Deliberately
not fixed here: league-scoping the commissioner dependency touches 38 route
declarations and is an authorization redesign, not Stripe removal.

---

## 7. Revision history

| Rev | Date | Change |
|---|---|---|
| 1 | 2026-08-05 | First issue. Records the Stripe removal, supersedes the Finding 5.2-1 sole-writer invariant, and states the replacement in force. |
