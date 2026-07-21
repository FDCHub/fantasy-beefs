# MODULE_SPEC — SPEC 1: Locked Challenge Proposal Lifecycle · Rev 3

**Project:** Fantasy Beefs
**Spec ID:** SPEC-1-PROPOSAL-LIFECYCLE
**Status:** FREEZE CANDIDATE (first formal architecture artifact)
**Findings covered:** A2, A3, lifecycle portions of A5, A7, Locked half of A9
**Deferred to Spec 2:** all escrow/ledger postings, capacity validation, reconciliation, `_challenge_reserved` retirement, `expire_challenge` transaction body
**Deferred to Spec 3:** entire Dynamic Handshake, per-side ceilings, Handshake/Final-Lock model+version authority, Final Lock
**Review treatment:** architecture review now; included as a **dependency in the Spec 2 Opus money-path package** (defines authoritative stake, accepted proposal, binding quote, counter-Anchor rules, and the escrow seam). No standalone posting-math gate.
**Build order:** 1 of 5. Blocks Spec 2.

**Recon basis:** four READ-ONLY passes against the live working tree, branch `fr-8.7-settlement-claim-first` @ `338fa82`. A fifth targeted pass confirmed no Wager Definition registry exists and that starter capture covers both teams (see §3, §11).

---

## 1. Purpose and non-goals

**Purpose.** Replace the single mutable `BeefChallenge` row with a **container + immutable versioned proposals**, so proposal-freeze semantics can be represented. Establish immutable `challenge_mode` and wager identity, proposal-scoped both-team starter snapshots, proposal-specific timing, the Refresh & Relock counter flow (a new frozen proposal that may change the Anchor), Locked no-reprice acceptance, actor-authorized transitions with concurrency serialization, and a negotiation `response_status` kept distinct from the canonical wager lifecycle.

**Non-goals:**
- **No money movement.** Issue/accept/refund/expiry postings are Spec 2. Spec 1 leaves named integration seams; it posts nothing.
- **No Dynamic Handshake.** Spec 1 defines `challenge_mode` and the *Locked* accept branch; the Dynamic branch is a defined boundary Spec 3 fills. Spec 1 must not freeze Dynamic pricing at proposal creation.
- **No pool/config work.** Specs 4/5.
- **No route enablement.** New-model issuance/response flows stay unreachable (feature-gated or unreleased-branch) until Spec 2 supplies escrow.

---

## 2. Existing-code facts (recon basis)

- `counter_challenge()` overwrites the same row (`beef_engine.py:1025-1028`); no versioning. Immutable-by-service today: `bet_type`, `line`, `side`, `player_id`, `amount`, `description` (docstring `:973`: "Bet type, week, and odds remain locked; only the stake changes"). Mutated by counter: `countered_amount`, `countered_at`, `status`, `expires_at`.
- `_capture_beef_starters` (`beef_engine.py:516-552`) captures **both** teams (`for team_id in (challenger_team_id, challenged_team_id)`, `:528`), first `N_START` (=9) roster players per team by `Roster.id`. Single call site: `issue_challenge` at `:773`. Idempotent. `BeefStarter` stores raw `team_id` (`schema.py:340`), no role flag; role derived at read time by matching against challenge participants (`:844-847`).
- **No** Wager Definition registry, no `wager_type`/`definition_id`/`definition_version`/`market_type` anywhere (Pass-5). Wager identity today = `bet_type` string (`:297`) + `line` (`:299`) + `side` (`:300`) + `player_id` (`:301`) + `description` (`:302`). The only "registry" is the in-memory `POOL_BET_TYPES` list (`pool_engine.py:57-62`), scoped to pool picks, unpersisted — not applicable to beefs.
- No `challenge_mode`/`is_locked`/`is_dynamic` and nothing derivable (Pass-2 §4).
- Single `amount` (+ `countered_amount`); odds already asymmetric and persisted (`:304-307`).
- One-counter rule enforced (`:979`).
- Acceptance reprice unconditional at `:919-927`, single shared call (Pass-2 §2).
- No withdrawal/revive paths (Pass-2 §2).
- Settlement escrow-sourced, unequal-escrow-tolerant (`settlement_engine.py:600-621`, Pass-3 §1) — **Spec 1 keeps these reads intact.**
- `expires_at` lives only on the challenge today; per-challenge kickoff lock computed in-engine.

---

## 3. Schema model

Three tables. Spec 1 owns structure and immutability; Spec 2 funds the stake fields. **No Wager Definition registry** — wager identity lives directly on the challenge (Pass-5 outcome three).

### 3.1 `BeefChallenge` (container) — immutable wager identity

Owns immutable wager identity a counter may not change:
- `id` (PK)
- `league_id`, `week`
- `challenger_team_id`, `challenged_team_id` (participants; fixed at creation)
- `challenge_mode` — **immutable**, CHECK `IN ('locked','dynamic')`, non-null, no update path
- `wager_type` — the immutable wager class (Moneyline/Spread/O-U). **A counter may not change this.** Replaces the current free-string `bet_type` on the challenge as the immutable class anchor; CHECK constrains valid values.
- `response_status` — negotiation state only (§4): `offered|countered|accepted|declined|expired|cancelled`
- `active_proposal_id` — FK → `BeefProposal`, must belong to this challenge
- `accepted_proposal_id` — FK → `BeefProposal`, null until acceptance, must belong to this challenge
- `active_response_expires_at` — **cached** convenience copy of the active proposal's deadline (proposal is authoritative, §3.2)
- `revived_from_challenge_id` — nullable audit lineage only (§8)
- `created_at`, `updated_at`

There is **no `wager_definition_id` / `wager_definition_version`** and no FK to any registry. None exists in the tree; introducing one would create an unapproved subsystem.

### 3.2 `BeefProposal` (immutable version) — frozen resolved quote

Insert-only; **never updated after creation**, even once inactive. Owns the frozen resolved quote and covered-entity snapshot.

**Provenance / identity:**
- `id` (PK, immutable proposal ID)
- `challenge_id` (FK)
- `version_number` — monotonic within challenge; `UNIQUE(challenge_id, version_number)` (§3.4)
- `version_kind` — CHECK `IN ('initial','counter')`
- `proposing_team_id` — who put this frozen proposal on the table
- `created_at`

**Timing (proposal is authoritative for its own deadline):**
- `response_expires_at`
- `proposal_lock_at` — authoritative earliest-covered-kickoff timestamp for *this* proposal's covered starters
- `schedule_source_ref` — schedule source/version or integrity reference used to derive `proposal_lock_at`
- **Effective response deadline** = `min(created_at + 60 minutes, proposal_lock_at)`. A counter may change covered starters and therefore its lock; the initial proposal's historical deadline stays reproducible after the pointer moves.

**Frozen resolved market terms (proposal owns these; challenge owns the class):**
- `line`, `side`, `player_id` (where applicable), and covered-market params
- covered-entity snapshot via `BeefProposalStarter` (§3.3)

**Money fields — mode-qualified semantics:**
- `anchor_stake_cents` — proposed fixed Anchor
- `quoted_derived_stake_cents` — Derived Stake displayed on this proposal
- `quoted_funded_pot_cents` — displayed funded pot for this proposal
- `anchor_team_id`, `derived_team_id` — the original issuer is **always** the Anchor side, even across a recipient-authored counter (A4; role bound to identity, not authorship)
- optional displayed payout/net-win values if the cards require them

**Authority by mode:** Locked — the selected proposal's quoted values become authoritative. Dynamic — quoted values are **immutable offer information only**; Spec 3 Handshake creates authoritative accepted stakes and ceilings.

**Pricing provenance (reproducible quote):**
- `pricing_model_id`, `pricing_calc_version`
- `projection_source_id` (dataset/source)
- `projection_retrieved_at`
- `projection_input_snapshot` (exact input snapshot) or immutable reference to it
- `anchor_win_probability`, `derived_win_probability`
- `anchor_odds`, `derived_odds`, `anchor_moneyline`, `derived_moneyline`
- `pricing_input_hash` — integrity hash of the pricing inputs

For Dynamic these describe the **offer quote only**, not later Handshake authority (Spec 3 adds separate records).

**Display:**
- `display_terms` — human-readable card terms. **Explicitly non-authoritative.** Structured fields govern; `display_terms` may never disagree with them.

### 3.3 `BeefProposalStarter` (proposal-scoped, both teams)

Replaces challenge-scoped `BeefStarter`:
- `id` (PK)
- `proposal_id` (FK → BeefProposal) — **not** challenge-scoped
- `team_id`, `player_id`, `nfl_team`
- `UniqueConstraint(proposal_id, team_id, player_id)`

Every proposal captures **both** teams (§6). `team_id` stores raw team id; role is derived by matching against challenge participants (mirrors current `BeefStarter` semantics).

### 3.4 Integrity constraints

- `UNIQUE(challenge_id, version_number)` — prevents two callers minting the same version (§9).
- `active_proposal_id` and `accepted_proposal_id` must reference proposals whose `challenge_id` equals this challenge.
- `challenge_mode`, `wager_type` immutable post-insert.

### 3.5 Proposal authority — Locked vs Dynamic

> A `BeefProposal` stores the complete immutable terms **presented for acceptance**. For **Locked** mode, the selected proposal becomes **authoritative** accepted pricing and covered-player snapshot. For **Dynamic** mode, it is the **immutable offer input** to the Spec 3 Handshake, whose resulting record becomes authoritative for accepted ceilings, model version, and pricing.

Spec 1 implements only Locked authority; the Dynamic accept path is a defined boundary handed to Spec 3.

**§3 ownership boundary (confirmed):** Spec 1 owns Anchor/Derived proposal fields and their immutability. Spec 2 owns capacity validation, escrow, reconciliation, and every BAB posting. One immutable proposal, one schema authority.

---

## 4. Negotiation status vs wager lifecycle

**`response_status` is negotiation-scoped only:** `offered → countered → accepted | declined | expired | cancelled`, and `countered → accepted | declined | expired | cancelled`.

**Terminal within negotiation scope** (permanently closes negotiation; Spec 2 refund attach points): `declined`, `expired`, `cancelled`.

**`accepted` is action-closed for negotiation but is NOT a terminal wager outcome.** The accepted wager continues through its **own** canonical lifecycle — `Offered → Accepted → Pending → Final | Push | Void` — governed by the Bet rows and settlement, not by `response_status`. Terminal-protection logic keyed on negotiation status must never block an accepted wager from Final Lock or settlement.

Downstream, by mode:
- **Locked:** because no repricing action remains after acceptance, the Bet rows ordinarily enter **Pending atomically at acceptance** (via Spec 2's accept transaction). The challenge's `response_status='accepted'`; the wager is Pending.
- **Dynamic:** the challenge remains in the accepted/Handshake lifecycle until **Spec 3 Final Lock** transitions the wager to Pending. Spec 1 sets `response_status='accepted'` and hands off; it does not move the Dynamic wager to Pending.

This prevents a challenge card's status from being read as settlement state.

---

## 5. Market authority — remove ambiguous duplication

`BeefChallenge.wager_type` is the **immutable wager class**. The proposal stores the **frozen resolved market terms** — line, side, player reference where applicable, covered entities, odds, stakes, and pricing provenance. A counter may alter the Anchor Stake and lineup-derived quote but **may not change `wager_type`**.

The wager class lives **once**, on the challenge. The proposal does **not** carry an independent, freely-set bet type. The simpler and recommended design is **not to duplicate** it: the proposal references the challenge's `wager_type`. If a redundant copy is retained on the proposal for snapshot completeness, it is explicitly a **frozen redundant snapshot** and Spec 1 **enforces equality** with the challenge's `wager_type` at proposal creation (reject on mismatch). No Wager Definition registry is referenced or introduced.

---

## 6. Starter snapshot ownership (both teams)

Starters move to **proposal-scoped**. Each proposal — initial and every counter — captures its **own** frozen snapshot of **both** teams: issuer lineup, recipient lineup, projections for both, covered player IDs for both. Even when only the recipient changed their Yahoo lineup, both sides are re-captured. A counter must be **independently reproducible** and may not inherit one side's starters from the initial proposal via an implicit join. Migrate `_capture_beef_starters` (`:516-552`), which already captures both teams, from per-challenge to per-proposal capture.

---

## 7. Flows

### 7.1 Initial offer

`issue_challenge()`:
1. Row: create `BeefChallenge` — immutable `challenge_mode`, `wager_type`, participants, week, `response_status='offered'`.
2. Create initial `BeefProposal` (`version_number=1`, `version_kind='initial'`, `proposing_team_id=challenger`), freezing §5 market terms, §3.2 timing (compute `proposal_lock_at`, set `response_expires_at`), stake fields, and full pricing provenance.
3. Capture `BeefProposalStarter` for **both** teams.
4. Set `active_proposal_id`; cache `active_response_expires_at`.

**Seam to Spec 2:** escrow-at-issue (A1). The challenge+proposal+starters+issuer-escrow **commit together** (§10) — Spec 1 does not commit the negotiation state before Spec 2's escrow. The route stays gated until Spec 2 lands (§13).

### 7.2 Refresh & Relock (counter)

Recipient refreshes lineup and proposes a **new Anchor Stake** (A7 — a counter may change the Anchor; that is its economic function):
1. **Row-lock the challenge** (§9). Reload/validate `response_status='offered'` (one-counter rule; `countered`/terminal rejected).
2. Pull **both** teams' updated lineups; recompute the quote and `proposal_lock_at` for the new snapshot.
3. Allocate `version_number=2` **under the lock**; create `BeefProposal` (`version_kind='counter'`, `proposing_team_id=recipient`) with its own both-sides starters, recomputed pricing+provenance, and the proposed Anchor/Derived pair. `wager_type` unchanged (§5).
4. Repoint `active_proposal_id`; set `response_status='countered'`; refresh cached deadline.
5. Original proposal untouched (immutable history).

**Seam to Spec 2:** counter-time **capacity validation only, no money movement** — `required_top_up = max(0, proposed_anchor_cents − challenge_escrow_balance_cents)` validated against issuer **Available to Bet under Spec 2's source-aware funding contract** (current-week `min` + `wallet`), plus the recipient's **full** Derived capacity under that same contract. (Spec 1 does not freeze a wallet-only availability model; the source-aware `min`+`wallet` contract is owned by Spec 2 §4.) No recipient escrow exists yet. Proposal + starters + pointer/status update **commit together** (§10).

### 7.3 Locked acceptance

Accept selects `active_proposal_id`:
1. **Row-lock the challenge** (§9). Revalidate `response_status`, active proposal, deadline not passed, actor authorization (§8).
2. Set `accepted_proposal_id`, `response_status='accepted'`.
3. **No reprice** (Locked half of A9): `_compute_odds_from_inputs` at `:919-927` removed from the Locked path; accepted terms read from the frozen proposal. The `:886-889` `live_inputs` fetch is Locked-path unnecessary.

**Seam to Spec 3:** accept branches on mode —
```
if challenge_mode == 'locked':   <select frozen proposal — Spec 1>
if challenge_mode == 'dynamic':  <Handshake — Spec 3 boundary>
```
Spec 1 implements only Locked; Dynamic is a defined boundary (gated until Spec 3), not a throwing stub.

**Seam to Spec 2 (A8):** selected proposal + Bet-row creation + escrow reconciliation (Anchor migration to Bet escrow) + recipient Derived escrow + accepted references + authoritative audit **commit together in one transaction** (§10). For Locked, Bet rows enter Pending atomically here. Settlement reads stay intact.

### 7.4 Terminal transitions

- **Decline** → `response_status='declined'`.
- **Cancel** (issuer withdrawal) → `response_status='cancelled'` (canonical `Cancelled`, not a new "withdrawn").
- **Expire** (TTL or kickoff lapse) → `response_status='expired'`, driven by a **scheduled job + response-path invocation**, never by list reads.

**Seam to Spec 2 (A5/A6):** each terminal-from-open transition's **refund + state transition + audit commit together** (§10). The `expire_challenge` transaction body (row-lock, verify open + deadline passed, **reconcile actual challenge escrow to expected funded Anchor, fail closed on missing/partial with a recorded reconciliation error**, refund, set `expired`, commit once) is Spec 2. Spec 1 removes the current in-read expiry mutation structurally and defines the resulting state.

---

## 8. Actor authorization & Revive

**Transition authorization:**

| State | Actor | Allowed |
|---|---|---|
| `offered` | recipient | accept, counter, decline |
| `offered` | issuer | cancel |
| `offered` | system | expire |
| `countered` | original issuer | accept, decline |
| `countered` | countering recipient | read-only |
| `countered` | system | expire |
| `countered` | anyone | **no re-counter** |

Once a counter is on the table, the issuer may **only** accept or decline (adopted model).

**Revive** (Response Card ruling): original issuer only; produces a **new challenge ID, new proposal ID, fresh timestamps/odds/stakes/starters/escrow**; no relationship reopening the old record. Optional `revived_from_challenge_id` audit lineage only. Revive is a fresh `issue_challenge()`, not a lifecycle edge.

---

## 9. Concurrency & first-valid-commit

Every state-changing operation (counter, accept, decline, cancel, expiry) must serialize on the challenge:
1. `SELECT … FOR UPDATE` the challenge row.
2. Reload and validate `response_status`.
3. Validate `active_proposal_id` (still the proposal being acted on).
4. Allocate the next `version_number` under the lock (counter path).
5. **First valid commit governs.** Later callers reload the committed result and return deterministically (e.g., "already countered," "already accepted," "already expired").

Enforced by `UNIQUE(challenge_id, version_number)` and the same-challenge FK constraint on `active_proposal_id`/`accepted_proposal_id`. Prevents: two counters minting version 2; accept selecting a proposal that ceased to be active; accept-vs-decline / accept-vs-cancel / response-vs-expiry races.

---

## 10. Atomicity with Spec 2

Spec 1 **must not** commit a lifecycle state and then call Spec 2. When enabled, each integrated transition is one atomic unit:
- **issue:** challenge + proposal + both-sides starters + issuer escrow — together.
- **counter:** proposal + starters + pointer/status update — together (capacity validation is read-only, no posting).
- **accept:** selected proposal + Bet rows + escrow reconciliation + accepted references + audit — together.
- **decline/cancel/expire:** refund + state transition + audit — together.

Spec 1 may **unit-test pure transition logic** independently, but no integrated service commits the Spec 1 half before the Spec 2 half. State, ledger, and audit writes commit atomically (system protocol).

---

## 11. Compatibility / migration — fail-closed gate

Current `_capture_beef_starters()` records **both** challenger and challenged teams. If legacy rows exist, initial-proposal starter identity can likely be associated with an initial proposal. **However, no automatic migration is authorized**, because legacy rows lack versioned proposal ownership, counter-specific starter snapshots, and immutable proposal pricing history (old counters overwrote in place; old accepted rows may have been repriced in place).

**Fail-closed existence gate:**
```
Before migration:
1. Count BeefChallenge rows.
2. Count BeefStarter rows.
3. Count related Bet rows.
4. If ALL relevant counts are zero → clean schema transition (drop/recreate, no backfill).
5. If ANY exist → STOP. Inspect starter completeness AND proposal pricing sufficiency.
   No automatic backfill is authorized until that evidence is reviewed in a separate plan.
```

The read-only production existence check happens **before** migration design is finalized and before any migration runs. The remembered FR-5.13 zero-row invariant is **not** sufficient authority to skip the count.

Legacy `the_lineup` on the Bet `bet_type` CHECK (`schema.py:207`) is untouched by Spec 1 (Spec 4's concern; flag so it isn't swept).

---

## 12. Tests required

- **Immutability:** counter never mutates prior proposal (original row byte-stable); no `BeefProposal` field updatable post-insert.
- **Versioning & provenance:** `version_number` monotonic; `UNIQUE(challenge_id, version_number)` enforced; `version_kind`/`proposing_team_id` correct for initial vs counter; N proposals independently reproducible from stored provenance.
- **Timing:** effective deadline = `min(created+60m, proposal_lock_at)`; a counter's lock recomputed from its own starters; initial proposal's historical deadline still reproducible after pointer moves.
- **Wager identity:** `wager_type` immutable (rejects updates); a counter cannot change the wager class; proposal market fields (`line`/`side`/`player_id`) remain internally valid for that `wager_type`; if a redundant proposal bet-type snapshot is retained, it must equal the challenge's `wager_type`.
- **Mode immutability:** `challenge_mode` rejects updates; CHECK rejects invalid mode.
- **Both-sides starters:** each proposal owns a both-teams set; counter re-captures both; no cross-proposal join. Confirm both challenger and challenged coverage per proposal where relevant.
- **Negotiation vs lifecycle:** `declined`/`expired`/`cancelled` terminal for negotiation; **`accepted` nonterminal** — assert an accepted Locked challenge remains eligible for downstream settlement; Locked accept yields Pending Bets atomically; Dynamic accept does not move to Pending (awaits Spec 3).
- **Locked no-reprice:** accepted Locked terms equal frozen proposal terms exactly; no odds drift.
- **Role assignment:** `anchor_team_id` stays the original issuer after a recipient counter.
- **Actor authorization:** each cell of §8 table enforced; issuer cannot counter; countering recipient is read-only on `countered`; no re-counter.
- **Concurrency:** simulate two counters (only one gets version 2, other returns deterministically); accept-vs-decline, accept-vs-cancel, response-vs-expiry races resolve to first-valid-commit.
- **Atomicity:** no integrated service commits Spec 1 state before Spec 2's escrow/refund (assert single-transaction boundary when enabled).
- **Display non-authority:** `display_terms` never overrides structured fields; a divergence is a test failure.
- **Revive:** original-issuer-only; new challenge + proposal IDs; fresh everything; optional `revived_from_challenge_id` lineage; no edge from terminal.
- **Reachability:** no route can create a new-model challenge without the Spec 2 escrow service (feature gate / unreleased-branch integration), proven by unreachability, not throwing stubs.

---

## 13. Explicit dependencies on Spec 2

| Seam | Spec 2 finding | Spec 2 supplies |
|---|---|---|
| **issue** | A1 | escrow-at-issue posting to `escrow:challenge:{id}`, atomic with issue |
| **counter** | A7 | capacity validation (`required_top_up` + recipient Derived), read-only |
| **accept** | A8 | reconciliation, Anchor→Bet-escrow migration, recipient Derived escrow, Bet creation, atomic |
| **decline/cancel/expire** | A5, A6 | refund postings + `expire_challenge` fail-closed reconciliation, atomic |
| **stake fields** | A4 | validation and funding of the Anchor/Derived fields Spec 1 persists |

**Deployment consequence.** Spec 1 schema and pure lifecycle build and test before Spec 2, but the new lifecycle cannot be **enabled** in a money-live environment until Spec 2 fills the seams (else challenges issue with no escrow). Keep routes feature-gated or land Specs 1 and 2 together on an unreleased branch. They may land incrementally but cannot be independently enabled. Tests prove unreachability, not stub-failure.

**Review treatment.** Spec 1 gets architecture review now and is a **named dependency in the Spec 2 Opus money-path package** — it defines which stake is authoritative, which proposal is accepted, which quote binds, how counters alter the Anchor, and where escrow attaches. No standalone posting-math gate (Spec 1 posts nothing), but not independent of the money-path review.

---

## Genuine open items

**None.** Both prior open items are closed by Pass-5 recon:
1. Starter capture confirmed to cover **both** teams (`_capture_beef_starters:528`).
2. No Wager Definition registry exists, and Spec 1 will **not** introduce one — immutable `wager_type` lives directly on `BeefChallenge`.

No remaining open architectural issue in Spec 1. Rev 3 is the freeze candidate.
