# B2 Group 2 — Season Allocation Contract of Record
## Revision 1 — first durable contract

**Status:** Contract of record. Established, not amended.
**Branch:** `b2/stripe-removal-season-allocation`
**Fork point and HEAD:** `3813779785efc16604ac59f7e0e17a0813a92b84`
**Date:** 2026-08-02
**Scope:** season allocation, the allocation gate, and the Group 2 code
correction pass. This revision authorizes no application, schema, migration, or
test behavior change. It authorizes only the documentary writes named in this
closeout.

---

## 1. Establishment, and what this file is not

No prior durable Group 2 season-allocation contract existed. A sweep of every
tracked `.md` and `.txt` file in the repository for `season_allocation`,
`allocation_gate`, `stripe-removal` and `Group 2` returned zero hits. The Group 2
contract lived only in thread state.

This file establishes that contract as its first revision.

The task was originally written as "amend the Group 2 contract of record." That
framing was wrong. There was nothing to amend. R-4 is corrected to "establish the
Group 2 season-allocation contract of record as first revision." The correction is
recorded here rather than silently applied, so the wording change does not
resurface later as an unexplained divergence.

**This file does not amend or supersede `SPEC_B2_v1.md`.** That document covers a
different scope: Stripe decouple and shortfall sweep, closing Findings 5.3 and 5.4
against `get_buyin_gate()` and `get_league_economy_stop()`. It remains a DRAFT
awaiting Opus Math Review on its Sections 4 and 6. The two documents share the
letter "B2" and the identifier `buy_in_paid`. They share nothing else. Neither
governs the other.

### 1.1 — Superseded reviewer ruling

An earlier reviewer ruling proposed a count-based `SeasonAllocationResult`.
**That ruling is superseded by this contract.** The implemented interface is
retained exactly as built. No interface change is authorized. The reasoning is
recorded at §4.1.

The supersession is recorded in writing so that a future reader comparing the
reviewer record against the shipped interface finds the divergence already
explained.

---

## 2. Season authority

The allocation season is **`config.ALLOCATION_SEASON`**, referenced explicitly
and by that name.

It is **not** `config.SEASON`. That name does not govern here.

It is **not** equated with `config.CURRENT_SEASON`. The allocation season is a
distinct authority. Any future code or document that substitutes the current
season for the allocation season is in violation of this contract.

---

## 3. The five-state model

Five states, evaluated **inside the transaction, before any write**.

| # | State | Outcome |
|---|---|---|
| 1 | no rows | create the complete allocation atomically |
| 2 | complete + match | return the existing result; nothing posted, nothing mutated |
| 3 | partial | `PartialAllocationError`; no mutation |
| 4 | conflicting | `ConflictingAllocationError`; no mutation |
| 5 | no teams | `NoTeamsError`; no mutation |

**This state machine is the idempotency mechanism.**

### 3.1 — The unique index is a race guard, not the idempotency path

`uq_season_allocation_league_team_season` is the **final race guard only**.

**Its violation is not the idempotency path.** Idempotency is decided by state 2,
inside the transaction, before any write. The index catches the narrow window
where two transactions both pass state evaluation and race to write. A constraint
violation is therefore an exceptional outcome, never the normal replay route.

This distinction is load-bearing. Any future change that routes replay through a
caught constraint violation would convert a proven in-transaction decision into an
exception-driven one, and would silently retire the state machine.

### 3.2 — Commit count

The authoritative rule:

- **At most one commit per invocation.**
- **Exactly one commit** on create.
- **Zero commits** on replay.
- **Zero commits** on every error path.

### 3.3 — Transaction ownership and caller isolation

The service takes ownership of the transaction on the supplied Session. The
caller supplies the Session; the service commits once on create and rolls back on
replay and every error path. A caller must not pass a Session carrying
uncommitted work it expects to survive or control.

Caller isolation is **inherited**, deliberately. The service does not set,
elevate, or verify an isolation level.

**READ COMMITTED is retained intentionally.** Two reasons:

1. Elevating to REPEATABLE READ would convert benign replays into `IntegrityError`.
   Replay is a normal expected path here, not a fault.
2. It is not reliably settable in any case. `get_league_economy_stop()` has already
   opened the transaction by the time the service is reached, and an isolation
   level cannot be changed after a transaction begins.

### 3.4 — Known divergence in the module's own docstring

`economy/season_allocation.py` contains an internal inconsistency, recorded here
and **not corrected in this documentary pass**.

The module's opening summary states the operation runs "with ONE top-level
commit." The module's own authoritative COMMIT COUNT section states the precise
rule reproduced at §3.2 above.

The opening summary is **overbroad**. It reads as though every invocation commits
once. Replay commits zero times. Every error path commits zero times. A caller
who trusted the summary would expect a commit on replay and would specify wrong
behavior downstream.

**This contract uses the COMMIT COUNT rule. The opening summary is not adopted
into this contract at any point.**

No change to the Python file is authorized by this revision. Correcting the
docstring requires separate authorization.

---

## 4. Retained result interface

`SeasonAllocationResult` is retained as implemented. Nine fields:

| Field | Meaning |
|---|---|
| `league_id` | the league activated |
| `season` | `config.ALLOCATION_SEASON` |
| `team_ids` | the teams covered |
| `buyin_cents` | per-team buy-in |
| `wallet_cents` | per-team wallet |
| `reserve_cents` | per-team reserve |
| `total_buyin_cents` | buy-in × team count |
| `created` | which success path was taken |
| `posting_ids` | postings made by **this** invocation |

### 4.1 — Success-path invariant

- **`created = True`** — this invocation created the rows and the postings.
- **`created = False`** — a complete matching allocation already existed. This
  invocation wrote nothing at all.
- **`posting_ids` is empty on replay because that invocation created no postings** —
  **not** because the existing posting identifiers are unknown.

The implemented interface was independently reviewed and retained. `team_ids`
preserves the identity of the teams covered; `created` structurally represents the
whole-league all-or-nothing success path; `posting_ids` provides an audit handle
for postings made by this invocation; and `total_buyin_cents` exposes the headline
conservation figure. The earlier count-based reviewer ruling is therefore
superseded.

Whole-league operation: all teams or none. No partial allocation is a success
state.

---

## 5. The gate surface

`auth/allocation_gate.py`, SHA-256
`98657F17D3E3FCEE917FCA22E464BF9D9079C2E31430B44A3BC774CB37D3D5C0`, 96 lines.
Verified by direct source read on 2026-08-02.

`get_season_allocation_gate` is a **per-route FastAPI dependency, not global
middleware**. It guards six routes in `api/main.py`:

| Route | Line |
|---|---|
| `/bets/place` | 511 |
| `/bets/straight` | 782 |
| `/bets/spread` | 803 |
| `/bets/over_under` | 824 |
| `/bets/prop` | 845 |
| `/beef/challenge` | 1125 |

All other routes are unguarded by this dependency.

Evaluation order inside the gate:

1. commissioner role → return, bypassing everything below;
2. `current_user.team_id is None` → return;
3. `Team` row missing → return;
4. `League` row missing **or** enforcement inactive → return;
5. no qualifying `SeasonAllocation` → raise
   `status.HTTP_402_PAYMENT_REQUIRED`.

The `SeasonAllocation` lookup is **season-qualified**, filtering `league_id`,
`team_id`, and `config.ALLOCATION_SEASON` together. A GM holding only a
prior-season row is still blocked. An unqualified existence check would let last
season's row open this season's gate.

The gate no longer reads `User.buy_in_paid`. That column survives in the schema as
DEBT-3 and is simply no longer consulted here.

### 5.1 — Two policy-read implementations

Two independent policy-read implementations exist, both in
`auth/allocation_gate.py`:

1. `get_allocation_enforcement_active()` at line 41, called by the status route at
   `api/main.py:1473`;
2. `get_season_allocation_gate()` at line 50, which reads
   `league.buyin_enforcement_active` inline at line 78, and serves as the
   dependency on the six gated routes.

Compatibility aliases in `api/main.py` and `payments/stripe_connect.py` expose
those same implementations under legacy names. They add public import names, not
policy logic, and do not create additional implementations.

`set_buyin_enforcement_active()` in `payments/stripe_connect.py` is a writer, not
an enforcement-decision reader.

Classified as policy-drift debt in the Findings Register at §24.2.

---

## 6. Concurrency evidence, and its limits

Uniqueness under concurrency is enforced by the unique index (§3.1). Two proofs
exist, and they are not of equal weight.

**m1 is the load-bearing proof.** It holds an uncommitted row and forces the
contender to block on the unique index. Overlap is structural, so m1 always
overlaps. The concurrency claim rests here.

**m2 is corroboration only.** Its `overlapped` count came in at 2, 1 and 3 across
three runs. Overlap is intermittent by construction. If m2 is ever dropped for
flakiness, the concurrency claim survives unchanged on m1. **m2 must never be
cited as the sole proof.**

**Not observed:** a concurrent replay *loser* under contention. The tests did not
produce one. Recorded as an observation gap, not as a proven absence.

**Sequential replay is proven separately** by scenario (g), independent of m1 and
m2.

---

## 7. Verification evidence of record

| Item | Value |
|---|---|
| Interpreter | Python 3.12.9 only, `C:\Users\frase\b2_venv\Scripts\python.exe` |
| System Python 3.13 | used for nothing |
| Assertions | 108 passed, 0 failed |
| Runs | three consecutive |
| Database | local Docker `postgres:16`, `localhost:5433`, container `fb_pg16_b2` |
| `DATABASE_URL` | empty on every invocation |
| Production contact | none |

**R-1 negative control.** The broad `except ValueError` was temporarily restored.
The route tests were observed to fail. It was reverted. `api/main.py` was then
verified byte-identical by SHA-256. The guard has teeth — proven by observed
failure, not assumed.

**R-5 money-path inventory.** Zero surviving `buy_in_paid` money-path readers.

Method correction, recorded because it changes how future sweeps must run:
`git grep` searches tracked files only. The new modules are untracked. A `git grep`
sweep alone would have returned a **false clean**. Any completeness sweep must
include untracked files.

---

## 8. R-10 — integrity classification

`economy/championship.py` and `reports/standings.py` are **unchanged Group 1
additions**. They appear in the Group 2 integrity manifest solely because the
manifest hashes all untracked files. They are not Group 2 work and carry no
Group 2 change.

### 8.1 — Sealed integrity checkpoint

The Group 2 code-correction checkpoint is sealed at **78 untracked entries**,
grown from a 71-entry baseline by exactly seven authorized additions. Zero
baseline entries were missing or changed.

Baseline manifest SHA-256:
`956B28CDE45E602754A2CF92C0B79655D95D37689A0486FEBB0F7DF180BBD62A`

The seven authorized additions:

| Path | SHA-256 |
|---|---|
| `auth/allocation_gate.py` | `98657F17D3E3FCEE917FCA22E464BF9D9079C2E31430B44A3BC774CB37D3D5C0` |
| `db/migrations/migrate_season_allocation.py` | `782CF3E8AC88D4159A8A2DB8B01F9A157BAF039F9A39C4F9DA495C790FEEE516` |
| `economy/__init__.py` | `E3B0C44298FC1C149AFBF4C8996FB92427AE41E4649B934CA495991B7852B855` |
| `economy/championship.py` | `D74BC6D6965BF0FA53886544F54E7E9365B882060DEB8E6B92A66A1B8727383A` |
| `economy/season_allocation.py` | `3D33C54EDA7792D71F765105209756BEB4245CCBEFC262CBFC10DBB91CB49F1D` |
| `reports/standings.py` | `9E58F560C1253978684522BBC3EAF82078712BD9455544138C784A6532FFC7C2` |
| `test_season_allocation_pg.py` | `06845BC3750DBE2B32A3E9CFBA34BA6C71D652F1DC53BCF7BAAFEBA762417226` |

`economy/season_allocation.py`'s hash differs from the pre-correction run. R-2,
R-8 and R-4 all edited it. Expected.

**`economy/__init__.py` hashes to the SHA-256 of zero bytes.** The file is empty,
correct for a package marker. Recorded because this is the one manifest line where
a hash match carries no content evidence: an empty file and a truncated file hash
identically. Classified as identified-by-intent, not proven-by-hash.

### 8.2 — Sealed tracked diff

Six files, +160 / −116.

| File | Changed lines |
|---|---|
| `api/main.py` | 95 |
| `config.py` | 5 |
| `db/schema.py` | 36 |
| `payments/stripe_connect.py` | 134 |
| `reports/settlement_report.py` | 2 |
| `wallet/faab_wallet.py` | 4 |

Current file hashes:

| File | SHA-256 |
|---|---|
| `api/main.py` | `d93d61e07318edf8540b24414b9cdece1bdd679b440b6a84ad091be75964dc0c` |
| `economy/season_allocation.py` | `3d33c54eda7792d71f765105209756beb4245ccbefc262cbfc10dbb91cb49f1d` |
| `test_season_allocation_pg.py` | `06845bc3750dbe2b32a3e9cfba34ba6c71d652f1dc53bcf7baafeba762417226` |

**Line-ending caveat.** Git reports that `config.py` and
`reports/settlement_report.py` will have LF replaced by CRLF on next touch. Any
future byte-identity claim on those two files must use the Git blob ID. A
working-tree SHA-256 will diverge for reasons unrelated to content.

---

## 9. R-7 — deployment order

**Not authorized.** Recorded for when it is.

1. Read production enforcement state — **under separate authorization**.
2. Run the migration.
3. Activate allocations.
4. Verify rows, ledger postings, and trial balance.
5. Enable enforcement.

### 9.1 — Pre-deploy checks

- Production `buyin_enforcement_active` is **unknown** and must be measured before
  deployment, under separate read-only authorization.
- Production `buy_in_paid` distribution is **unknown** and must be measured before
  any partial-revert decision, under separate read-only authorization.
- Enforcement is enabled **last**, after migration, activation, and verification.
- Confirm `config.ALLOCATION_SEASON` is the intended season before activation.

### 9.2 — HTTP 402 blast radius

Blocking occurs only where all of the following hold:

- the league has `buyin_enforcement_active` true;
- no qualifying `SeasonAllocation` row exists for that team, league, and
  `config.ALLOCATION_SEASON`;
- the GM is not a commissioner and holds a valid `Team` row and a valid `League`
  row;
- the request targets one of the six gated betting or challenge routes.

Unaffected:

- all routes other than those six;
- GMs caught by a fail-open branch — no `team_id`, or a missing `Team` row;
- commissioners, who bypass at the first check.

Within those bounds the impact is total: betting and challenge issuance is the
whole product surface an affected GM uses. That is why step 1 precedes the
migration and why enforcement is enabled last. The ordering is not stylistic.

**No production resource may be contacted under this revision.**

---

## 10. Revision history

| Rev | Date | Change |
|---|---|---|
| 1 | 2026-08-02 | Established. First durable contract. No prior contract existed. Gate surface verified by direct source read. |