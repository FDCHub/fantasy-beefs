# MODULE_SPEC — SPEC 2: Challenge Escrow & Atomic Acceptance · OPUS-READY

**Project:** Fantasy Beefs
**Spec ID:** SPEC-2-CHALLENGE-ESCROW-ACCEPTANCE
**Status:** OPUS-CLEARED — Opus Math Review completed; MS-2-1 rejected as unreachable, MS-2-2 and MS-2-3 approved and integrated. Both pre-build recons complete (`post()` caller inventory: 10 production callers, all `session=db`; Wallet-row lock-order check: no existing Wallet row locks, so Spec 2 establishes the first canonical ascending-team_id order — no conflict). Architecture review complete (four corrections integrated: challenge-id flush ordering, exact reversal linkage, counter idempotency, fail-closed reconciliation across every pre-acceptance refund). Ready for implementation planning, subject to the normal migration/existence gates.
**Findings covered:** A1 (escrow at issue), A4 (asymmetric stakes), A5 money portions (refunds), A6 (fail-closed expiry), A7 (counter capacity math), A8 (atomic acceptance + reconciliation)
**Depends on:** Spec 1 Rev 3 (frozen) — bundled as a named dependency in this spec's Opus package
**Couples with:** Spec 5 (weekly-min account lifecycle) — Spec 2 owns the account *contract*; Spec 5 conforms
**Seams to:** Spec 3 (Dynamic acceptance reuses Spec 2's pre-acceptance funding primitives)
**Build order:** 2 of 5.

**Recon basis:** four READ-ONLY passes, branch `fr-8.7-settlement-claim-first` @ `338fa82`. Pass 2 (SPEC 2 pass 2) established that `min:{team}:{week}` accounts, source-split funding, provenance records, protocol-event identity, and deterministic locking all do **not** exist and must be built.

---

## 0. Scope statement (read first)

Spec 2 is **not** "move wallet to escrow." It is the first **source-aware Versus funding and refund subsystem** in Fantasy Beefs. It builds:
1. real issuer Anchor escrow at issue (replacing soft reservation), drawn `min`-first-then-wallet;
2. the `min:{team}:{week}` consumption/refund contract (Spec 5 later owns creation/release/sweep);
3. immutable **ordered** funding-leg provenance;
4. source-faithful refunds via strict reverse-leg reversal;
5. asymmetric Anchor/Derived stake placement;
6. atomic Locked acceptance with issuer reconciliation and recipient Derived escrow;
7. the `expire_challenge` fail-closed reconciliation transaction;
8. a protocol-event + immutable audit layer with deterministic row locking.

**Pre-acceptance funding is shared by both modes.** Issue escrow, counter capacity validation, and decline/cancel/expire refunds apply to **Locked and Dynamic** challenges alike — a Dynamic issuer also escrows the Anchor at issue. Spec 2 owns the complete **Locked** acceptance path; Spec 3 owns **Dynamic** acceptance (Handshake), reusing Spec 2's source-split funding, provenance, challenge escrow, event, and locking primitives.

---

## 1. Purpose and non-goals

**Purpose.** Give the Spec 1 lifecycle its money, correctly sourced and provenanced, atomically and idempotently, under explicit locks.

**Non-goals:**
- **Not the weekly-min lifecycle.** Spec 2 *consumes and refunds* `min:{team}:{week}` and *defines its contract*. Spec 5 *creates, funds, releases, and sweeps* it.
- **Not settlement.** Settlement stays as-is (escrow-sourced, unequal-tolerant, `settlement_engine.py:600-621`); Spec 2 preserves `escrow:{bet_id}` reads unchanged.
- **Not Dynamic acceptance.** Spec 2 funds the shared pre-acceptance path and the Locked accept path; Dynamic accept is a named seam to Spec 3.
- **Not Championship/Frozen accounts** (Spec 5, B6/B7).
- **Not the FAAB transfer float-divergence full fix** (flagged §14; scope call, likely Spec 5 or its own finding).

---

## 2. Live-code facts (recon basis)

- **No escrow at issue.** `issue_challenge` makes zero `ledger_post` (`beef_engine.py:725-733`, comment `:723-724`). Stake is soft only via `_challenge_reserved`.
- **`_challenge_reserved`** (`wallet_manager.py:87-97`), 6 call sites: accept check (`beef_engine.py:640`), issue check (`:726`), counter check (`:1016`), transfer availability (`faab_wallet.py:655`), 2 display models (`wallet_manager.py:112`, `faab_wallet.py:218`). Filters `challenger_team_id`, statuses `pending`+`countered`.
- **`escrow:{bet_id}`** is the only escrow identity (`beef_engine.py:604`, settlement reads `settlement_engine.py:557,560,600,601,606,607,973`). No `escrow:challenge:`. Account strings are arbitrary caller-supplied (no registry); ledger guards prefix-match `escrow:` (`ledger.py:189`).
- **No `min:{team}:{week}` account, no source-split helper, no provenance record** anywhere (Pass-2 §1). The only weekly-min artifact is `League.economy_stop_weekly_min_cents` (`schema.py:60`) — a threshold value, not a fund account.
- **Money representation split:** ledger `amount_cents` (BigInteger, authoritative, `ledger.py:61`) vs float `Wallet.balance` (`schema.py:193`), `Bet.amount` (`:220`), `Transaction.amount` (`:249`), `BeefChallenge.amount`/`countered_amount` (`:298,319`). `_place_beef_side:571` re-checks float `wallet.balance < amount`. `_to_cents = round(amount*100)` (`beef_engine.py:75-79`); stricter `_dollars_to_cents` uses Decimal + rejects sub-cent (`ledger.py:129-147`).
- **`post()`** (`ledger.py:223-310`) takes `entries, door, session` only; mints its own `posting_id = uuid.uuid4()` (`:294`); no external event/idempotency arg. Session path defers commit (`:298-299`); session=None commits (`:308`). Only idempotency-like guard: `wager_settled` + escrow-at-0 (`:188-196`). Ledger rows have no `challenge_id`/`bet_id`/`event_id`.
- **No `FOR UPDATE`** in issue/counter/accept (Pass-2 §6). `_balance_of_in_session` is a lock-free SUM (`ledger.py:89-105`). REPEATABLE READ set at `beef_engine.py:876-877` **after** the transaction autobegan at `:791` — too late to be reliable.
- **Audit:** five feed-log functions write mutable `FeedEvent` (`league_feed.py`); all commit separately from the money except lazy-sweep expiry. **No immutable challenge audit table** (only settlement's FR-8.7 `settlement_recovery_audit`). **No cancel path, no cancel log.**
- **No source provenance** on any record (Pass-2 §7). Refund reconstructable only to the single wallet today.

---

## 3. Account model (ruled)

**Pre-acceptance (new):** `escrow:challenge:{challenge_id}` — holds the issuer's funded Anchor while the offer/counter is live. Applies to **both** modes.

**Post-acceptance (existing, preserved):** `escrow:{anchor_bet_id}`, `escrow:{derived_bet_id}`.

Acceptance migrates reconciled challenge escrow → Anchor Bet escrow; separately funds Derived Bet escrow. Both are wager-obligation accounts under the broader GM-escrow concept. Settlement is **not** rewritten into pooled escrow — `escrow:{bet_id}` reads stay intact.

**Weekly-min account (contract owned here):** `min:{team_id}:{week}`. Spec 2 owns:
- min-first consumption; wallet fallback;
- ordered source-leg provenance; source-faithful refunds;
- account balance / reconciliation rules;
- funding and refund ledger doors.

Spec 5 conforms to this contract and owns: creating/funding the balance, weekly release calculations, unspent sweeps, season/config behavior. **Until Spec 5 ships, an absent `min` account reads as zero and funding falls entirely to wallet.** Any league configuration requiring funded weekly-min accounts stays disabled until Spec 5.

**Ledger linkage requirement:** account strings are insufficient audit identity. Spec 2 adds structured protocol-event linkage (§7).

---

## 4. Source-aware funding model (ruled — the scope increase)

**Consumption order, per commitment (integer cents):**
1. Read `min_available = balance_of("min:{team}:{week}")` (zero if absent).
2. `min_leg = min(min_available, required_cents)`.
3. `wallet_leg = required_cents − min_leg`.
4. Post: debit `min:{team}:{week}` by `min_leg` (if > 0), debit `wallet:{team}` by `wallet_leg` (if > 0), credit the escrow obligation by `required_cents`.
5. Record the funding legs **in order** (§5): min-leg first, wallet-leg second.

Both legs are optional (min-only, wallet-only, or mixed). The single escrow credit always equals the total. Every posting sums to zero by construction (§9 proofs).

**Spec 5 coupling:** Spec 2 reads/debits `min:{team}:{week}`; it does not seed or replenish it. The account string, integer-cent balance semantics, and the consumption/refund doors are defined here; Spec 5 references this spec for the shape.

---

## 5. Provenance model (ruled — ordered legs, not totals)

**Cumulative totals are insufficient.** Strict reverse-order refund (§11) needs the exact leg sequence, which two running totals (`min_source_cents`/`wallet_source_cents`) cannot reconstruct. Provenance is an **ordered, append-only funding-leg ledger.**

**`ChallengeFundingLeg`** (new table), append-only:
- `id` (PK)
- `challenge_id` (FK)
- `event_id` (FK → protocol event, §7)
- `sequence_number` — monotonic within the challenge's funding history (strict order for reversal)
- `source_account` — `min:{team}:{week}` or `wallet:{team}`
- `amount_cents` — the funded amount on this leg (positive = funded, negative = reversed)
- `leg_kind` — CHECK `IN ('fund','reverse')`
- `reverses_funding_leg_id` — FK → `ChallengeFundingLeg.id`, **null for `fund` legs, required for `reverse` legs.** The exact original fund leg this reversal draws from. This immutable link is what makes partial strict-reverse refunds safe.
- `posting_id` — the ledger posting-group id this leg belongs to
- `created_at`

A funding event writes one or more `fund` legs in order; a refund/true-up-down writes `reverse` legs, each explicitly linked via `reverses_funding_leg_id` to the exact original fund leg it draws from, in strict reverse `sequence_number` order (§11).

**Remaining-reversible invariant.** Every original `fund` leg has a deterministically derivable:
```
remaining_reversible_cents(fund_leg) =
    fund_leg.amount_cents
    − SUM(abs(reverse_leg.amount_cents) for reverse_leg where reverses_funding_leg_id == fund_leg.id)
```
A reverse leg may draw at most `remaining_reversible_cents` from its target fund leg. Without this linkage, `sequence_number` alone cannot tell how much of a partially-consumed leg remains — repeated partial reductions could reverse the same original leg twice or skip a partially-consumed one. The link + invariant make each reversal provably exact.

The escrow obligation's current source composition is derivable by summing legs; order is preserved for reversal; per-leg remaining balance is derivable from the linkage. Never mutated — reversals are new rows, not edits.

---

## 6. Integer-cent authority (ruled)

**Authoritative:** `BeefProposal.anchor_stake_cents`, `BeefProposal.quoted_derived_stake_cents`, `LedgerEntry.amount_cents`, `ChallengeFundingLeg.amount_cents`, ledger-derived escrow balances.

**Compatibility/display only:** `Wallet.balance`, `Bet.amount`, `Transaction.amount`, legacy `BeefChallenge.amount`/`countered_amount`.

**Spec 2 rules:**
- All validation, calculation, posting, provenance, and reconciliation use integer cents.
- **Remove** the `_place_beef_side:571` float `wallet.balance < amount` re-check from the Spec 2 path — the cents-authoritative funds check in `_verify_wallet_available` (superseded by §8 lock+re-read) governs.
- Legacy float writes become mirrors: `Bet.amount = stake_cents / 100`, `Transaction.amount = posted_cents / 100`, written only after the authoritative cents value is fixed. The float never drives validation, escrow, refund, payout, true-up, or reconciliation.
- External dollar inputs use strict `_dollars_to_cents` (Decimal, rejects sub-cent). Never `round(float*100)` on the money path.

---

## 7. Event / idempotency model (ruled)

**Protocol-event identity** for every state-changing operation: `challenge_issue`, `challenge_counter`, `challenge_accept`, `challenge_decline`, `challenge_cancel`, `challenge_expire`.

**`challenge_counter` is a protocol event even though it posts no ledger.** Countering changes authoritative challenge state, creates an immutable proposal, repoints the active proposal pointer, and performs balance-sensitive capacity validation — so it must be idempotent and auditable. A duplicate `challenge_counter` event id returns the **original** counter result (the already-created proposal version), never a second proposal.

**`ChallengeProtocolEvent`** (new immutable table):
- `event_id` (PK, caller-visible, `UNIQUE`)
- `event_type` (CHECK against the six above)
- `challenge_id` (FK)
- `proposal_id` (FK, nullable — set for accept)
- `actor_identity` (team id or `system`)
- `league_id`, `season`, `week`
- `effective_at`
- `prior_state`, `resulting_state`
- `ledger_posting_ids` (the posting-group UUIDs this event produced)
- `result_code` — success or a deterministic failure code (e.g., `reconciliation_error`)
- `spec_version`
- `created_at`

`UNIQUE(event_id)` suppresses duplicates; a repeated delivery returns the **original committed result**, posts nothing new. This is the domain idempotency key; the ledger's internal `posting_id` remains the posting-group id only.

**Ledger linkage.** Each ledger posting references the protocol event. Two options — outline flags for Opus:
- (a) add an optional `event_id` argument to `post()`, stored on `LedgerEntry`, or
- (b) an `event_link` side-table keyed by `posting_id → event_id`.
Recommended: (a) — one nullable column + one optional arg. **This modifies the ledger primitive shared by every money path.** Blast-radius item: a complete `post()` caller inventory ships in the Opus package before the primitive changes (does not block drafting).

**Audit atomicity.** The `ChallengeProtocolEvent` record commits **atomically** with the state transition, ledger postings, proposal/Bet references, and funding provenance. `FeedEvent` stays a non-authoritative presentation record, written only **after** commit. This fixes the current split where feed logs commit in a separate transaction from the money (`beef_engine.py:948` etc.).

---

## 8. Lock order / concurrency (ruled)

REPEATABLE READ is not the primary control (set after autobegin, `:791` vs `:877`). Use explicit row locks in one deterministic order. Because ledger balances are aggregate (unlockable), Spec 2 uses **one lockable mutex per team-season funding scope** — the `Wallet` row serves as the serialization mutex (its float balance is non-authoritative, but the row locks). Flag: confirm no other path locks Wallet rows in a conflicting order (micro-recon before build).

**Deterministic lock sequences:**

**Issue** (shared both modes). The `escrow:challenge:{challenge_id}` account cannot be constructed until the challenge has an id, so the challenge is **created and flushed** (not committed) before posting:
1. Lock issuer Wallet row (`SELECT ... FOR UPDATE`).
2. Create the `BeefChallenge` container and `db.flush()` to obtain `challenge_id` (flush ≠ commit — atomicity intact).
3. Create the initial proposal + both-sides starters (Spec 1).
4. Re-read `min` + `wallet` ledger balances inside the lock; validate available ≥ Anchor (cents).
5. Post funding legs → `escrow:challenge:{challenge_id}` (now constructible); write ordered provenance legs; write protocol event + immutable audit.
6. Single commit. Feed log after commit.

**Counter** (shared both modes):
1. Lock challenge row.
2. Lock issuer Wallet row, then recipient Wallet row **in ascending team_id** (deadlock avoidance).
3. Validate issuer `required_top_up` (§10) + recipient full Derived capacity, all cents.
4. Insert new proposal + repoint `active_proposal_id` (Spec 1).
5. Write the `challenge_counter` protocol event (idempotency + audit), no ledger posting.
6. **No money posting.** Single commit.

**Locked acceptance** (§12):
1. Lock challenge row.
2. Lock selected proposal / verify immutable ownership.
3. Lock both Wallet rows **in ascending team_id**.
4. Re-read `min`, `wallet`, `escrow:challenge` ledger balances inside locks.
5. Validate all funding conditions (cents).
6. Create Bet rows.
7. Reconcile issuer challenge escrow to selected Anchor (true-up, §12).
8. Migrate Anchor challenge-escrow → `escrow:{anchor_bet_id}`.
9. Fund recipient Derived → `escrow:{derived_bet_id}` (source-split).
10. Persist provenance, state, immutable audit, event linkage.
11. Single commit.

**Refund (decline / cancel / expire — all pre-acceptance full-refund paths):**
1. Lock challenge row.
2. Lock issuer Wallet row.
3. Verify event not already completed (idempotency).
4. Reconcile actual `escrow:challenge` balance vs expected challenge escrow (`SUM(unreversed funding legs)`, §5 — **not** the active proposal's Anchor) — **fail-closed for every path** (§11), not expiry only.
5. Reverse funding legs to original sources (strict reverse order, §11).
6. Set state + immutable audit. Single commit.

**First-valid-commit** governs all paths; later callers observe the committed result deterministically.

---

## 9. Issue transaction

Sequence per §8 Issue. The challenge is created and `flush()`ed for its id **before** the postings below, so `escrow:challenge:{challenge_id}` is constructible; flush is not a commit, so all of it remains one atomic transaction. Posting drawn min-first.

**Posting table — Anchor 1000¢, 600¢ min available, 400¢ from wallet:**
```
min:{team}:{week}                 -600
wallet:{team}                     -400
escrow:challenge:{challenge_id}  +1000
                             sum =    0  ✓
door = "challenge_issued"      event = challenge_issue:{event_id}
funding legs (ordered):  seq1 min  600 (fund)
                         seq2 wallet 400 (fund)
```

**Posting table — Anchor 1000¢, min absent (reads zero), all wallet:**
```
wallet:{team}                    -1000
escrow:challenge:{challenge_id}  +1000
                             sum =    0  ✓
funding legs:  seq1 wallet 1000 (fund)
```

---

## 10. Counter capacity validation

Per §8 Counter. **Validation only — no money moves.**

- **Issuer top-up:** `required_top_up = max(0, proposed_anchor_cents − escrow_challenge_balance_cents)`. Validate `required_top_up` against issuer available (`min + wallet`, cents). The issuer already has the original Anchor funded in `escrow:challenge`; only the deficiency is checked — a raise from 1000¢ to 1200¢ validates 200¢, not 1200¢.
- **Recipient Derived:** validate the **full** `quoted_derived_stake_cents` against recipient available (min + wallet). The recipient has nothing escrowed yet.

Zero-sum proof trivial: no postings. Proposal insert + pointer repoint are Spec 1 writes, committed together (§8).

---

## 11. Decline / cancel / expire refund transactions

Shared shape: reverse funding legs **strict reverse order** (most-recently-funded leg refunded first).

**Reverse-order rule (ruled).** Refund reverses legs in descending `sequence_number`. Example — a challenge funded then topped-up:
```
Initial funding:  seq1 min 600, seq2 wallet 400
Top-up:           seq3 min 150, seq4 wallet 50
```
A 200¢ reduction reverses seq4 then seq3:
```
escrow:challenge:{id}   -200
wallet:{team}            +50     (reverse seq4)
min:{team}:{week}       +150     (reverse seq3)
                   sum =   0  ✓
new legs: seq5 wallet -50 (reverse), seq6 min -150 (reverse)
```
A further 200¢ reduction then reverses back into seq2:
```
escrow:challenge:{id}   -200
wallet:{team}           +200     (reverse remaining wallet from seq2)
                   sum =   0  ✓
```
Never proportional — proportional division invents rounding questions and doesn't reconstruct actual historical movements. Reversal is reproducible from the immutable ordered legs.

**Full refund** (decline/cancel/expire of an untouched issue). A pre-acceptance full refund reverses every original `fund` leg's `remaining_reversible_cents`, processing original funding legs in descending `sequence_number`. `reverse` rows are never themselves treated as refundable funding legs. Each new reversal row must reference the exact original `fund` leg through `reverses_funding_leg_id`. Example (§9 first case):
```
escrow:challenge:{id}   -1000
wallet:{team}            +400   (reverse seq2)
min:{team}:{week}        +600   (reverse seq1)
                   sum =    0  ✓
door = "challenge_refunded"
```

Under Spec 2, partial reversal of challenge escrow occurs only inside the atomic Locked acceptance transaction. No committed pre-acceptance state may contain partially reduced challenge escrow. If a future protocol adds such a state, the refund composition and tests must be reopened.

**Cancel** introduces the missing cancel path + cancel audit (no cancel log exists today). Issuer withdrawal → `cancelled` + full refund.

**Fail-closed reconciliation rule (A6) — applies to EVERY pre-acceptance refund path: decline, cancel, expire, and any pre-acceptance full-refund.** Counters move no money (§10); until acceptance the challenge escrow holds whatever was funded at issue. A counter may change the *proposed* Anchor but not the *funded* Anchor. Pre-acceptance refunds therefore reconcile against the funding provenance, **not** the active proposal's Anchor. Before any refund or terminal state change, require:
```
expected_challenge_escrow_cents = SUM(unreversed challenge funding legs)   # §5 provenance

balance_of("escrow:challenge:{id}") == expected_challenge_escrow_cents
```
Do **not** compare against the active proposal's Anchor. On mismatch (missing or partial escrow): **post nothing; do not set Declined, Cancelled, or Expired**; write a `reconciliation_error` protocol-event/audit result; leave the challenge unresolved for recovery. "Balance > 0" is not sufficient — a partial balance is invalid. This is not expiry-specific: decline or cancel could otherwise silently terminalize a challenge with stranded or missing escrow, which is the same money-correctness bug as a silent expiry.

**Acceptance is the separate target.** At Locked acceptance (§12) only, the funded amount reconciles against the **selected proposal's Anchor** via the true-up (no-op / raise / lower). Load-bearing example: issue funds 1000¢, an active counter proposes 800¢ — a pre-acceptance expiry refunds the full **1000¢** (funded legs), while acceptance would true-up **down to 800¢** (proposal Anchor), releasing 200¢. Reconciling the pre-acceptance refund against 800¢ would strand 200¢ of actually-funded escrow.

---

## 12. Atomic Locked acceptance (A8 — load-bearing)

Single-commit transaction per §8 Locked acceptance. Three true-up branches, all provenance-faithful.

**Anchor role vs proposal authorship (funding rule).** The selected proposal determines the accepted Anchor amount, but the funding obligation follows `anchor_team_id`, not `proposing_team_id`. The original issuer remains the Anchor across a recipient-authored counter. Every Anchor top-up or release therefore debits or credits the original issuer's funding sources. The recipient independently funds the selected proposal's full Derived stake. (This applies equally to the §8 Locked-acceptance sequence: "verify immutable ownership" checks the proposal's identity, but the funding side of the true-up is always the Anchor team's.)

**Acceptance-time capacity revalidation.** Counter-time validation does not reserve BAB. After locking the challenge, selected proposal, and both funding-control rows, acceptance must re-read authoritative `min`, Wallet, and challenge-escrow balances. It must revalidate:
1. the issuer's required Anchor top-up, if any; and
2. the recipient's full Derived stake.

If either amount cannot be funded, acceptance fails atomically: no Ledger posting, funding leg, Bet row, accepted reference, or state transition is written. The protocol records or returns a deterministic `insufficient_acceptance_capacity` result, and the challenge remains in its existing open state until another valid action or its deadline. No partial acceptance or partial funding is permitted.

**Common case — accepted own offer unchanged, Anchor 1000¢ (600 min/400 wallet), Derived 750¢ (450 min/300 wallet):**
```
# true-up: A_accept == A_issue → no-op
# migrate Anchor challenge-escrow → Anchor Bet escrow (provenance carries to bet):
escrow:challenge:{id}    -1000
escrow:{anchor_bet_id}   +1000     sum=0 ✓
# fund Derived, min-first:
min:{derived}:{week}      -450
wallet:{derived}          -300
escrow:{derived_bet_id}   +750      sum=0 ✓
# pot = 1000 + 750 = 1750¢, escrow-sourced at settlement ✓
```

**Raised counter — Anchor 1000¢→1200¢, top-up 200¢ (min-first: 150 min/50 wallet); Derived 750¢:**
```
# true-up top-up (min-first on the 200 delta), appends legs seq3/seq4:
min:{issuer}:{week}       -150
wallet:{issuer}            -50
escrow:challenge:{id}     +200      sum=0 ✓   (challenge escrow now 1200)
# migrate:
escrow:challenge:{id}    -1200
escrow:{anchor_bet_id}   +1200      sum=0 ✓
# Derived:
min:{derived}:{week}      -450
wallet:{derived}          -300
escrow:{derived_bet_id}   +750      sum=0 ✓
# pot = 1200 + 750 = 1950¢ ✓
```

**Lowered counter — Anchor 1000¢→800¢, release 200¢ strict-reverse-order (last legs seq2 wallet 400 / seq1 min 600 → reverse seq2 first):**
```
# release 200 by reversing seq2 (wallet) first:
escrow:challenge:{id}     -200
wallet:{issuer}           +200      sum=0 ✓   (reverses 200 of the 400 wallet leg)
# migrate remaining 800:
escrow:challenge:{id}     -800
escrow:{anchor_bet_id}    +800      sum=0 ✓
# Derived as above
# pot = 800 + 750 = 1550¢ ✓
```
The release order follows the recorded leg sequence, not a fixed "wallet first" or "min first" preference — here seq2 happened to be wallet. A different funding order produces a different refunded mix, and that is correct: it reproduces actual history.

**Seam to Spec 3:** `if challenge_mode == 'dynamic'` → Handshake (Spec 3). Spec 2 does not run the Locked reconciliation for Dynamic.

---

## 13. Dynamic seam to Spec 3

Pre-acceptance funding (issue escrow, counter validation, refunds) is **shared** — Spec 2 owns it for both modes. Dynamic **acceptance** is Spec 3: the Handshake funds both ceilings, freezes model version, and writes the Handshake record, **reusing** Spec 2's source-split funding, ordered provenance, `escrow:challenge` account, protocol-event layer, and lock order. Spec 2 names the boundary and exposes these primitives as the shared contract so Spec 3 doesn't re-invent them.

---

## 14. Compatibility / migration

- **Retire `_challenge_reserved`** across all 6 sites (§2). Once real escrow posts at issue, the ledger `wallet:{team}` balance already reflects the debit; subtracting a soft reservation would double-count. The 4 functional gates switch to real-escrow-aware availability; the 2 display models read the new provenance instead.
- **New tables:** `ChallengeFundingLeg` (§5), `ChallengeProtocolEvent` (§7). Migrations written but unrun until Opus clears and the existence gate passes.
- **`min:{team}:{week}` consumption contract** defined here; account seeded by Spec 5.
- **FAAB `transfer()` float-mutation-without-ledger divergence** (Pass-2 §3): flagged, **not fixed here** — mutates `Wallet.balance`/`waiver_balance` as floats with no ledger posting. Scope call: likely Spec 5 or its own finding. Note so it isn't assumed fixed.
- **Existence gate** (same discipline as Spec 1): count existing beef rows before any migration; clean transition only if zero, else stop for reviewed plan.

---

## 15. Test matrix

- **Source split:** min-only, wallet-only, mixed, min-empty-reads-zero.
- **Provenance round-trip:** fund then full-refund returns the exact mix; ordered legs reconstruct correctly.
- **Strict reverse-order release:** lowered counter with an **unequal** min/wallet split (equal splits prove nothing) — assert the refunded mix matches recorded leg order, not proportional.
- **Reversal linkage invariant:** every `reverse` leg links to a specific `fund` leg; `remaining_reversible_cents` never goes negative; repeated partial reductions never double-reverse a leg or skip a partially-consumed one.
- **Counter idempotency:** a duplicate `challenge_counter` event id returns the original proposal version, does not create a second.
- **Fail-closed on decline/cancel too:** decline and cancel with a deliberately mismatched `escrow:challenge` balance → no refund, no terminal state, `reconciliation_error` audit (not expiry-only).
- **Raised counter top-up:** min-first on the delta; provenance legs appended in order.
- **All three A8 true-up branches** (no-op, raise, lower).
- **Unequal-escrow settlement** still closes `trial_balance` to 0.
- **Fail-closed expiry:** escrow == expected → refund; escrow ≠ expected → no refund, no Expired, `reconciliation_error` audit.
- **Idempotency:** duplicate issue/accept/refund returns the original result and posts once (`UNIQUE(event_id)`).
- **Deterministic lock order:** concurrent accepts by overlapping teams serialize by ascending team_id, no deadlock; two concurrent issues by one team can't both pass the funds check.
- **Integer-cent authority:** no float drives any decision; legacy floats equal `cents/100` exactly.
- **Event-audit atomicity:** protocol event + audit commit with the money; feed event only after commit; a crash before feed leaves the money+audit consistent.
- **REPEATABLE-READ non-reliance:** the concurrency test passes on explicit locks, not on the isolation set.
- **Anchor role vs proposal authorship:** recipient-authored counter raises the Anchor; assert the top-up debits the original issuer's sources, never the countering recipient's.
- **Acceptance capacity drift:** counter passes capacity validation, issuer or recipient spends BAB before acceptance, acceptance revalidation fails atomically, posts nothing, creates no Bets, and leaves the challenge open.
- **Full-refund iterator safety:** full refund processes only original `fund` legs and their remaining reversible amounts; `reverse` rows are never re-reversed.

---

## 16. Opus review package contents

- This spec (SPEC 2).
- **Spec 1 Rev 3 bundled** as named dependency (defines authoritative stake, accepted proposal, escrow seam — the money math sits on it).
- Every posting table with integer-cent zero-sum proof (§9, §11, §12).
- The source-split algorithm (§4) and strict reverse-order release rule (§11) with an unequal-split worked example.
- The `post()` event-linkage primitive change (§7) **plus a complete `post()` caller inventory** across the whole tree (blast-radius review before touching the shared primitive).
- The fail-closed expiry reconciliation (§11).
- The lock-order deadlock-avoidance argument (§8).
- Issues-only, table format (Name / Issue / Options / Recommendation & Reasoning), each finding approved individually by Fraser before any fix is built.

---

## 17. Dependencies

- **Spec 1 (frozen):** container/proposal/mode/stake-fields/lifecycle/seam call sites. Spec 2 fills issue/counter/accept/refund hooks.
- **Spec 3 (downstream):** Dynamic acceptance reuses Spec 2's shared pre-acceptance funding + primitives; Spec 2 names the boundary.
- **Spec 5 (paired, live coupling):** conforms to the `min:{team}:{week}` contract defined here (string, integer-cent balance, consumption/refund doors); owns creation/release/sweep. Until Spec 5 ships, min reads zero and funding is wallet-only; funded-min league configs stay disabled.

---

## Genuine open items

1. **FAAB transfer divergence (§14).** Scope decision: fix in Spec 5, or spin its own finding. Not resolved here.

*(The two pre-build recons — Wallet-row-as-mutex conflict check and `post()` caller inventory — are complete; results recorded in the header and in Findings Register v12 §3. No conflict found; Spec 2 sets the first canonical Wallet-lock order.)*
