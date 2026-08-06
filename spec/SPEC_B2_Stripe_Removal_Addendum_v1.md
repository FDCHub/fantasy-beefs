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

---

## 8. B-2 closure (Revision 1 addition, 2026-08-05)

B-2 was the last B2 blocker: the accepted championship distribution arithmetic
and remainder rule were reachable only through payout code deleted with the
Stripe surface, and would otherwise have been lost.

### 8.1 — Finding 5.2-3, Option A — the accepted rule, preserved

`economy.championship.championship_distribution(total_cents, split, order)`
returns `(place, team_id, pct, amount_cents)` per place, in `order`, numbered
from 1.

1. Each ordinary amount is `floor(total_cents * pct / 100)`.
2. The **entire** remainder after flooring every place goes to **first place**.
3. Therefore `sum(amount_cents) == total_cents` for every valid input.

Integer cents only — verified at AST level: zero true-division nodes, zero float
literals, one floor-division node. Invalid input raises `ValueError` and is never
silently normalised; `bool` is rejected explicitly because it is an `int`
subclass.

### 8.2 — What it is NOT

`championship_distribution()` is **arithmetic only**. It touches no database, no
session, no ledger, and posts nothing. **Internal Credits championship
settlement remains UNBUILT** and is not part of this package. Nothing here may
be read as evidence that a season can be settled.

Idempotent settlement and configurable payout split remain later decisions.
`ECONOMY_STOPS` does **not** define payout splits — the only splits in the
codebase are `reports.standings.DEFAULT_PAYOUT_SPLIT = [60, 30, 10]` and the
`LeagueTreasury.payout_split_json` column default.

### 8.3 — Season-funding invariant, and how it is enforced

**PRESERVED INVARIANT: at most one season-opening funding posting per
`(team, season)`.**

Enforced by removal of every alternative production writer, plus the
`SeasonAllocation` unique constraint on `(league_id, team_id, season)`. There is
**no cross-writer runtime exclusion check**, because after the Stripe removal
there is no second writer to exclude.

### 8.4 — Persisted ledger-door assertion

Source-level proof (the AST guard) is now paired with a runtime one. The B2
PostgreSQL suite reads persisted `LedgerEntry` rows back and asserts every
`reserve:%` row carries `door = "season_allocation"`.

**Scope, stated exactly:** the rows produced by that suite's own setup in the
disposable `_test` database. **No production database is inspected and no claim
is made about historical production rows.** Other SQLite suites deliberately
post reserve legs with `door="buy_in_paid"` / `"buy_in_tab"` as historical
pre-B2 fixtures; they are a different database and a different scope, and the
assertion was not weakened to accommodate them.

### 8.5 — FAAB top-up routes deregistered pending B6

`POST /faab/topup-bet`, `/faab/topup-waiver`, `/faab/topup-confirm` and
`/faab/apply-pending` are **no longer registered**. The temporary
request-and-confirm flow is not an acceptable permanent Credits issuance model:
it mints wallet balance with no counterparty and no ledger posting.

They remain unavailable until B6 provides a balanced ledger posting, an issuance
counterparty/account, approver identity, and request-to-credit provenance. The
underlying implementation in `wallet/faab_wallet.py` is retained as B6's starting
point. The read-only FAAB surface (`/faab/wallet`, `/faab/league`, `/faab/setup`,
`/faab/config`, `/faab/transactions`, `/faab/freeze`, `/faab/init-season`)
survives — this is a mint removal, not a feature deletion.

**RESIDUE, RECORDED NOT ASSUMED AWAY:**
`notifications/tuesday_sync.py::_step_apply_topups` still calls
`apply_pending_topups()`, which credits `FaabWallet.waiver_balance` directly, and
that pipeline is reachable via `POST /admin/tuesday-sync`. With the request
routes gone, no route can create an eligible pending record — but that is a
**database precondition, not a structural guarantee**. Neutralising the Tuesday
step is classified REQUIRED and is deliberately out of scope here.


---

## 9. Post-acceptance hardening (2026-08-05)

B2 acceptance is **not reopened**. These are bounded hardening items applied
after Groups 1 and 2 were accepted and B-1/B-2 closed.

### 9.1 - Tuesday-sync top-up mint structurally refused

`wallet.faab_wallet.apply_pending_topups()` now raises `TopUpsUnavailableError`
as its **first executable statement** - before any query, any `FaabWallet` read,
any status change and any ledger call. Verified structurally: the function's
first non-docstring AST node is a `Raise`.

Not an environment flag, and not a silent no-op - a no-op would report success
while applying nothing, which is worse than refusing.

`notifications/tuesday_sync.py::_step_apply_topups` catches it specifically and
records the step as "top-ups unavailable pending B6 issuance-ledger model" with
`applied_count = 0` and `unavailable = True`. The rest of the Tuesday pipeline
is unaffected, which is that module's established handling for a step that
cannot run.

**No registered or automated production path can now apply a legacy pending
top-up.** Proven in `test_stripe_removal_regression.py` Item 7 against a real
due pending row: status unchanged, waiver_balance unchanged, Wallet.balance
unchanged, pending_waiver_topup unchanged, no FaabTransaction added, no ledger
entry added - before and after the pipeline step runs.

### 9.2 - Gate tests retargeted to SeasonAllocation

The five stale failures are closed by **fixture retargeting**, not by weakening.
`test_buyin_enforcement.py` and `test_bet_funded_retirement.py` now seed a real
`SeasonAllocation` row for `config.ALLOCATION_SEASON`.

The row is inserted directly rather than produced by
`activate_season_allocation()`, which would also post the three-leg funding
entry and move `wallet:{team}`, invalidating each file's existing ledger-balance
assertions. **The gate is not patched or bypassed** - it still performs its own
season-qualified lookup against a real row. `buy_in_paid` is still written
alongside, so both suites keep proving the legacy column does not drive the
decision. No expected status code was weakened.

### 9.3 - Season-allocation league scoping: BLOCKED

**Not implemented. The route is NOT league-scoped, and is not recorded as such.**

No authoritative user-to-league relationship exists for commissioners:

- `User` has no `league_id`; `League` has no commissioner/owner column;
- there is no membership or commissioner-assignment table;
- the only structural path is `User.team_id` -> `Team.league_id`, and
  `User.team_id` is **nullable** - a commissioner need not own a team, and the
  gate code already handles `team_id is None`;
- the five models carrying both `user_id` and `league_id` (`BuyInRecord`,
  `PayoutRecord`, `StripeAuditLog`, `CommissionerRule`, `RuleAuditLog`) are
  **audit records of who performed an action**, not grants of authority.
  Deriving authority from `CommissionerRule.created_by_user_id` would be
  circular, and would fail for a commissioner who has created no rules.

Minimum decision needed: an explicit commissioner-to-league authority record
(a `league_commissioners` join table, or a nullable
`League.commissioner_user_id`), plus a product ruling on whether a commissioner
must own a team in the league they administer. **No schema was invented and no
name/email inference was used.** Recorded as an open REQUIRED finding.

### 9.4 - Distribution hygiene

- **Mismatched split/order is rejected deliberately.** The deleted payout
  implementation zipped and silently truncated, which could under-distribute the
  pot while appearing to succeed. Raising preserves the exact-distribution
  invariant. Tested in both directions.
- **Zero-percent first place still takes the remainder.** With `[0, 60, 40]`,
  place 1 floors to 0 yet receives the whole remainder - Option A is not
  special-cased on pct > 0. Note `[0, 100]` can never strand a remainder, since
  `total * 100 // 100` is exact; the suite asserts that rather than overstating.
- **Purity is now AST-verified by the committed test**, not by source-string
  inspection: zero `ast.Div` nodes, at least one `ast.FloorDiv`, zero float
  literals, no `float()`/`round()`, no DB/session/ledger call, and no
  Stripe/payment identifier anywhere in the body.
- **`order` is an already-ranked input**, best team first. The function assigns
  place 1 to `order[0]` and does not compute or verify standings; ranking is the
  caller's responsibility. Recorded in the docstring.

### 9.5 - Unchanged

Internal Credits championship settlement remains **unbuilt**. B6 remains
**unbuilt**. No new funding writer exists. `activate_season_allocation()`
remains the sole production writer of the season-opening posting.


---

## 10. Commissioner-to-league authority (2026-08-06)

B2 acceptance is **not reopened**.

### 10.1 - The local authority model

`league_commissioners` (model `LeagueCommissioner`, `db/schema.py`):

| Column | Type | Notes |
|---|---|---|
| `id` | Integer PK | autoincrement, repository convention |
| `league_id` | Integer NOT NULL | FK `fk_league_commissioner_league` -> leagues.id |
| `user_id` | Integer NOT NULL | FK `fk_league_commissioner_user` -> users.id |
| `source` | String NOT NULL | check `ck_league_commissioner_source` |
| `assigned_by_user_id` | Integer NULL | FK `fk_league_commissioner_assigned_by` -> users.id |
| `created_at` | DateTime NOT NULL | UTC default |

Unique constraint `uq_league_commissioner_league_user` on `(league_id, user_id)`.

**THE AUTHORIZATION KEYS ARE LOCAL IDS.** Authorization is decided by the
presence of a row - never by `User.role` alone, never by team ownership, never
by a Yahoo identifier.

**Commissioner authority is independent of team ownership.** `User.team_id` is
not consulted. A commissioner need not own a team in the league they
administer, and a GM granted an explicit row IS authorized - proven by test.

**Cardinality is many-to-many.** One user may hold rows for several leagues; one
league may have several commissioners or co-commissioners. The unique constraint
prevents only a duplicate of the same pair.

### 10.2 - Source values

- `yahoo_sync` - reconciled from Yahoo's commissioner designation. **Yahoo
  reconciliation is NOT built; no row carries this value.**
- `local_grant` - granted inside FantasyStakes by an existing authority,
  recorded in `assigned_by_user_id`.
- `bootstrap` - temporary authority at a first trusted import. **NOT built** -
  see 10.4.

`assigned_by_user_id` is nullable because bootstrap and Yahoo-derived rows have
no granting user. It is not an audit log; this package implements **no
revocation history**.

Yahoo reconciliation identifiers belong on `User` and `League`, not on this join
table: substituting a remote identifier for a local FK would make authorization
depend on an unreconciled system.

### 10.3 - The season-allocation route is league-scoped

`POST /league/{league_id}/season-allocation` now depends on
`require_league_commissioner`. **This is the only route narrowed.** Every other
commissioner route still uses the global `require_commissioner` and remains an
open finding.

Response ordering, a deliberate security decision:

- **401** unauthenticated / inactive - unchanged.
- **403** authenticated but not authorized for this league, returned **before**
  any league-existence lookup, so league ids cannot be probed by comparing 403
  against 404.
- **404** league genuinely absent - reachable only by a caller already
  authorized for that id.

### 10.4 - Bootstrap: BLOCKED, NOT IMPLEMENTED

**No bootstrap code was written.** The identity relationship it requires does
not exist.

1. **The Yahoo OAuth credential is NOT stored per user.** It lives in
   process-level files (`secrets/yahoo_oauth.json`, `secrets/private.json`)
   loaded at module import in `yahoo_auth.py`. There is no token table, no
   OAuth model, and no token column on `User`.
2. **Credential ownership cannot be proven.** One shared credential serves every
   request. `yahoo_auth.py` writes a `guid` into `secrets/private.json`, but
   nothing links that guid to a `User` row.
3. **There is no authenticated league-import boundary.** No route creates or
   updates a `League`. The only `League(...)` constructions are a dev helper in
   `db/schema.py` and the offline `seed_real_2025_season_LIVE.py`.

**Smallest missing local relationship:** a per-user Yahoo identity binding - a
unique nullable `User.yahoo_guid` (or a per-user credential row) populated at an
authenticated OAuth callback - **plus** an authenticated league-import route
that creates the `League` in the same transaction as the requesting user. Only
then can "this authenticated user performed the first trusted import" be
asserted rather than assumed.

No bootstrap was inferred from team ownership, email, display name, or global
role. Recorded as an open REQUIRED finding.

### 10.5 - Yahoo reconciliation remains unbuilt

Automated Yahoo commissioner synchronization is not in this package and requires
read-only payload evidence before any field is assumed. No Yahoo API call was
made to discover commissioner fields.

### 10.6 - R-H1 closed

A focused proof now exists: enforcement ACTIVE + `buy_in_paid = 1` + **no**
qualifying `SeasonAllocation` -> **HTTP 402**. The legacy column cannot
authorize access by itself. The complementary direction is retained: a valid
allocation passes with `buy_in_paid = 0`.

### 10.7 - U-1 and U-2 closed by construction

**U-1 - concurrent replay-loser returning `created=False`. CLOSED BY
CONSTRUCTION, not waived.** A concurrent loser that finds a complete matching
allocation takes the *same* state-2 branch already proven by scenario (g):
return the existing result, post nothing, commit nothing. The implementation
cannot observe whether another transaction overlapped it - there is no
concurrency-specific alternative behaviour to test, because none exists in the
code. The distinct concurrent path that *is* observable, the unique-constraint
race, is proven by (m1) and (m2).

**U-2 - direct-import proof of `economy.championship`. CLOSED** under the prior
reviewer rationale; `_championship_total` is now imported directly from
`economy.championship` by both `test_championship_payout.py` and
`test_stripe_removal_regression.py`.

Historical entries are preserved; this is an appended closure ruling.

### 10.8 - B6 top-offs

B6 remains an **MVP requirement** and remains **unbuilt**. Accepted flow:

> GM requests top-off -> authorized league commissioner approves -> balanced
> Credits-ledger issuance posts -> GM wallet receives Credits.

The league-authority model added here is a prerequisite for the "authorized
league commissioner approves" step. Nothing in this package implements the
issuance posting.
