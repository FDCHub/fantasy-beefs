# Fantasy Beefs — Findings Register v12.2

**Supersedes:** v12.1
**Date:** 2026-07-20
**v12.2 change:** added I-5 (championship payout placement authority) to Section 6 — a Spec 5 season-close finding with a shipped-code-fix flag: built Championship Pot pays by regular-season standings, ruling is finalized Yahoo postseason bracket placement; narrow default-source fix + new Yahoo bracket reader + fail-closed rule + `standings_order`→`placement_order` rename. Skunk unchanged. Spec 5 scope-impact block updated.
**v12.1 change (carried):** I-3 wording correction — skunk isolation now reads "assessments never debit Wallet or escrow, while the season payout credits the champion's Wallet."
**v12 update (carried):** three Opus Math Review dispositions for Spec 2 (Section 5) and the four economy/skunk reconciliation findings (Section 6: I-1 through I-4). All prior content carried unchanged from v11.

---

## Section 1 — The fifteen money-model findings (RULED)

Format: Finding / Ruling / Launch-blocker / Spec home.

### Group A — Locked/Dynamic money model

**A1 — Escrow-at-issue (soft reservation → real issuer Anchor escrow).**
RULED A1-a: issue posts real money to a challenge-scoped account `escrow:challenge:{id}`, drawn min-first-then-wallet. `_challenge_reserved` retired from availability math (all 6 call sites). Blocker: YES. Spec 2.

**A2 — Immutable versioned proposals.**
RULED A2-a: dedicated `BeefProposal` table (insert-only versions) + `BeefProposalStarter` (proposal-scoped, both teams). `BeefChallenge` becomes a container. Counter inserts a new proposal, never overwrites. Blocker: YES (Locked). Spec 1 (frozen Rev 3).

**A3 — Explicit immutable `challenge_mode`.**
RULED A3-a: `challenge_mode ∈ {locked, dynamic}` on the challenge container, immutable, CHECK-constrained. No derivable mode exists today. Blocker: YES. Spec 1.

**A4 — Asymmetric stake persistence.**
RULED A4-a: role-explicit fields on the proposal — `anchor_stake_cents`, `quoted_derived_stake_cents`, `anchor_team_id`, `derived_team_id`. Original issuer is always the Anchor side, even across a recipient counter. Settlement untouched (already escrow-sourced, unequal-tolerant). Blocker: YES. Spec 1 (fields) + Spec 2 (funding).

**A5 — Terminal refund protocol.**
RULED A5-a: decline → Declined, issuer withdrawal → Cancelled (canonical, not a new state), TTL/kickoff lapse → Expired. Each refunds the exact challenge escrow. Revive = new issuance, not a refund transition. Blocker: YES. Spec 1 (states) + Spec 2 (refund postings).

**A6 — Lazy-sweep expiry as money-writing read path.**
RULED (modified A6-c): remove money mutation from `get_pending_challenges`. Dedicated idempotent `expire_challenge` transaction (row-lock, verify open + deadline passed, fail-closed reconcile actual escrow to expected funded Anchor, refund, set Expired, commit once). No FR-8.7-style durable claim needed. Blocker: YES. Spec 2.

**A7 — Refresh & Relock counter escrow treatment.**
RULED: a counter MAY change the issuer Anchor Stake (its economic function). Counter creates a new frozen proposal; issuer escrow does not move; recipient money does not move; both capacities validated informationally only; money moves at acceptance. Counter-time issuer validation = `required_top_up = max(0, proposed_anchor_cents − challenge_escrow_balance_cents)`; recipient validates full Derived. Blocker: YES. Spec 1 (flow) + Spec 2 (capacity math).

**A8 — Atomic acceptance + issuer reconciliation.**
RULED A8-a (reordered): one transaction — lock, revalidate, create Bets, reconcile issuer challenge escrow to selected Anchor (true-up: refund excess / top up deficiency), migrate Anchor to Bet escrow, escrow recipient Derived, persist accepted-proposal + Bet refs + provenance + audit, commit once. Single-commit boundary preserved; explicit rollback added. Blocker: YES. Spec 2.

**A9 — Locked no-reprice vs Dynamic Handshake branch.**
RULED A9-a: branch on `challenge_mode`. Locked selects frozen proposal terms, no reprice (removes the unconditional `_compute_odds_from_inputs` at accept for Locked). Dynamic runs the full Handshake — the current reprice call is only a fragment; Dynamic infrastructure is greenfield. Blocker: YES. Spec 1 (Locked half) + Spec 3 (Dynamic half).

### Group B — Pool / config

**B1 — Bench Burn selectable but never settled.**
RULED B1-b default (build), B1-a only via explicit product de-scope. Until settlement exists, block unpaid picks immediately. FR-5.7 (RosterSlot capture) is BUILT; FR-5.8 (evaluator) is absent — build it. Blocker: YES. Spec 4.

**B2 — Worst Beat active despite protocol retirement.**
RULED B2-a: remove from pick/funding/settlement/display paths; historical rows stay readable. July-19 protocol retires it as duplicative of Skunk; live code still funds it. Blocker: YES. Spec 4.

**B3 — Offered/funded pool-set mismatch (`//3` denominator).**
RULED B3-a: dynamic allocation across enabled-and-funded pools; top-level indivisible remainder credits `championship:{league_id}` (NOT Special Teams). Denominator = count of enabled funded occurrences, not `len(POOL_BET_TYPES)`. Blocker: YES. Spec 4. Depends on B1/B2/B4 final funded set.

**B4 — Launch "The Lineup" Rank Pool absent.**
RULED B4-a default (build as Rank Pool), unless explicit de-scope. Legacy `the_lineup` single-party Bet is NOT equivalent (reuse metric helpers only after verifying inputs/tie behavior; not the lifecycle). Tie behavior across the 12-GM league is an unresolved product ruling before the Spec 4 draft. Blocker: YES unless de-scoped. Spec 4.

**B5 — League-level pool fee bound.**
RULED B5-a + B5-b: `100 ≤ weekly_entry_cents ≤ 500`, validate at service + API + DB CHECK; default → 100¢; commissioner confirms during league init; freeze at first accepted wager (see B6). Field already league-level (not per-pool as docs claimed). Blocker: YES (low-effort). Spec 5.

**B6 — Absence of season-fixed configuration enforcement.**
RULED: build reusable season-fixed config guard with field-specific freeze events — economy stop and pool fee freeze at FIRST ACCEPTED WAGER; unspent-min destination freezes at SEASON KICKOFF; no amendment may alter terms already referenced by an accepted wager. No freeze exists in code today for any setting. Blocker: partial (accepted-wager invariant + unspent-min = YES). Spec 5.

**B7 — Championship account scope inconsistency (NEW this line).**
RULED: canonical account is `championship:{league_id}`. Tree posts to BOTH bare `championship` (shortfall sweep) and `championship:{league_id}` (pool rollover) — different accounts, breaking league isolation and producing incomplete Championship balances. No new posting may use bare `championship`. Recon migration consequence of any existing bare-`championship` balance before implementation. Blocker: YES, Opus-gated. Spec 5. Fix before building new remainder/unspent-min postings so new code doesn't copy the wrong convention.

---

## Section 2 — Five-spec split (CONFIRMED) and build order (LOCKED)

Build order: **1 → 2 → 3 → 5 → 4.** (Specs 1+2 establish the shared challenge foundation; Spec 3 adds Dynamic without contaminating the stable Locked path; Spec 5 precedes Spec 4 because pool remainders/fees depend on a correct Championship account.)

- **Spec 1 — Locked Challenge Proposal Lifecycle.** A2, A3, A5 lifecycle portions, A7 flow, Locked half of A9. STATUS: FROZEN (Rev 3).
- **Spec 2 — Challenge Escrow & Atomic Acceptance.** A1, A4, A5 money, A6, A7 capacity math, A8. Shared pre-acceptance funding for both modes + complete Locked acceptance. STATUS: OPUS-CLEARED (Math Review complete; MS-2-1 rejected, MS-2-2/MS-2-3 approved and integrated — see §5). Ready for implementation planning.
- **Spec 3 — Dynamic Handshake & Final Lock.** Dynamic half of A9 + all Rev-7 machinery (greenfield subsystem: model/projection versions, Handshake record, ceilings, Final-Lock timestamp/trigger, refresh, official simulation, Adjustment/refunds, claim-first execution). STATUS: not started.
- **Spec 5 — League Economy Configuration & Account Identity.** B5, B6, B7. Canonicalize `championship:{league_id}`; fee bound/default/freeze; season-fixed enforcement; unspent-min destination + `frozen:{team_id}`; owns the `min:{team}:{week}` account lifecycle Spec 2 defined the contract for. **SCOPE EXPANDED (Section 6):** four-bucket $0-wallet topology (R1 integer-cent reserve formula, Yahoo-derived weeks replacing `×14`), `min_reserve:{team}` runway account (distinct from `reserve:{team}`), buy-in Door 1 postings, the skunk liability submodule (R2/R3, separately Opus-reviewable), and the championship payout placement-authority correction, Yahoo postseason-result reader, fail-closed pending behavior, and `placement_order` migration (I-5; shipped-code-fix flag). STATUS: not started.
- **Spec 4 — Pool Catalog & Settlement.** B1–B4. Bench Burn evaluator (on built RosterSlot capture), Worst Beat removal, The Lineup Rank Pool (new N-team metric), dynamic allocation. STATUS: not started. Open product ruling: The Lineup tie behavior.

---

## Section 3 — Pre-build recons (COMPLETE)

Both recons ran read-only against `338fa82` before the Spec 2 Opus submission. Neither reopened the Spec 2 draft.

- **`post()` caller inventory — COMPLETE.** 10 production call sites, all passing `session=db`; zero production callers use `session=None`. Reached from Beef, single bets, pools, settlement, shortfall sweeps, and buy-ins. Full blast radius for the §7 event-linkage change; the optional-trailing-arg + nullable-column change is source-compatible with the inventoried signatures (subject to a test matrix covering both `session=db` and `session=None`).
- **Wallet-row lock-order check — COMPLETE.** No path in the tree locks Wallet rows today (no `SELECT ... FOR UPDATE` / `with_for_update()` on Wallet). No existing conflicting order.
- **Result:** no conflict. Spec 2 establishes the first canonical ascending-`team_id` Wallet-lock order.

---

## Section 4 — Separate open findings (carried, not in the spec queue)

- **FAAB `transfer()` float divergence** — mutates `Wallet.balance`/`waiver_balance` as floats with no ledger posting (Pass-2 §3). Own finding; scope call Spec 5 or standalone. NOT folded into Spec 2.
- **FR-8.7 tests 6c/6d** — settlement claim-first test stream. Separate from spec-build work. Isolation-level watch-item (`SAWarning` REPEATABLE READ) must be understood before the concurrent-invocation test.
- **FR-8.8 Protocol Compliance Audit** — full P1–P8 money-path sweep. Position: after FR-8.7 tests + Opus code review, before final launch sign-off. Not imminent.

---

## Section 5 — Spec 2 Opus Math Review dispositions (2026-07-20)

Opus Math Review ran as a hard money-path gate against the Spec 2 Opus package (cover + Spec 2 Final + Spec 1 Rev 3). All posting tables verified zero-sum by hand; pre-acceptance-vs-acceptance reconciliation split confirmed correct. Three findings raised; each approved individually by Fraser. Two spec-edit approvals, one rejection with defensive cleanup. **Targeted corrections only — no reopening of the posting math; no second Opus round required unless an edit materially changes implementation semantics.**

### MS-2-1 — Rejected

**Disposition:** Rejected — unreachable under Spec 2's state machine.

**Reasoning:** A partial reversal against `escrow:challenge:{id}` occurs only inside the atomic Locked acceptance transaction. In that same transaction, the remaining challenge escrow migrates to `escrow:{anchor_bet_id}` before commit. Counter-time itself moves no money. Therefore, no committed state exists in which challenge escrow is partially reduced while the challenge remains open for decline, cancellation, or expiry.

**Premise (reopening condition):** This rejection depends on partial Anchor reductions remaining acceptance-atomic. If a future protocol introduces a pre-acceptance offer-reduction path that refunds part of challenge escrow while leaving the challenge open, this finding must be reopened.

**Defensive clarification accepted (→ Spec 2 §11 edit):** Pre-acceptance full refunds reverse each original funding leg's remaining reversible amount in descending original funding-leg sequence. They do not iterate blindly across all provenance rows.

### MS-2-2 — Approved

**Disposition:** Approved.

**Required clarification (→ Spec 2 §8/§12 edit):** Anchor true-up funding follows the Anchor role, not proposal authorship. Every Anchor top-up or release debits or credits `anchor_team_id`, which remains the original issuer, regardless of which team authored the selected proposal. The recipient separately funds the full Derived stake.

### MS-2-3 — Approved

**Disposition:** Approved.

**Required clarification (→ Spec 2 §12 edit):** Counter-time capacity validation creates no reservation. Acceptance must re-read and revalidate issuer top-up capacity and recipient Derived capacity under the transaction locks.

**Failure behavior:** If either party lacks required capacity at acceptance: post nothing; create no Bet rows; do not set `accepted_proposal_id`; do not change `response_status`; return and record a deterministic `insufficient_acceptance_capacity` result; leave the challenge open in its existing state until accepted successfully, declined, cancelled where authorized, or expired by its deadline. No partial acceptance or partial funding is permitted.

### Spec 2 edits applied (this disposition)

- **§11** — defensive full-refund wording (fund-leg remainders only; reverse rows never re-reversed) + the acceptance-atomic-only premise note.
- **§8/§12** — Anchor role clarification (funding follows `anchor_team_id`, not `proposing_team_id`).
- **§12** — acceptance-time capacity revalidation + fail-atomic branch.
- **§15** — three tests: Anchor-role-vs-authorship; acceptance capacity drift; full-refund iterator safety.

---

## Section 6 — Economy & Skunk reconciliation findings (2026-07-20, from UI/UX branch)

Source: `HANDOFF_Economy_Skunk_Reconciliation_v2.md` (My Ledger design session) and `FINDING_Championship_Pot_Postseason_Basis.md`, both grep-verified 2026-07-20. Five findings reviewed. I-1 through I-4 do not reopen Spec 2 (Findings 1/2 and account topology are Spec 5 domain, downstream of Spec 2; Finding 4 confirms Spec 2's real-escrow design; Finding 3 is independent). **I-5 is a separate shipped-code correction in the Spec 5 season-close path** — it fixes built, tested production behavior, not a design-forward spec. I-1 through I-4 recorded as design findings, no code in this thread. The economy/skunk handoff also carries three baked rulings (R1 championship-reserve integer-cent formula; R2 skunk liability accounts; R3 skunk tie split) — see the handoff for exact postings.

**The locked model:** four buckets, wallet starts $0. (1) `wallet:{team}` = $0, wagerable (winnings + top-offs only); (2) `min:{team}:{week}` = weekly, wagerable this week; (3) `min_reserve:{team}` = weekly runway, releases into #2, **NEW name — must NOT reuse `reserve:{team}`**; (4) `reserve:{team}` = championship reserve, season-end/title only.

### I-1 — Wallet-$0 vs Spec 2's funded-source assumption

**Disposition:** Spec 2 math **unchanged**. Its §4 examples merely demonstrate mixed-source funding; the source-split algorithm (min-first, wallet-fallback) stands whether wallet holds $0 or a seeded balance. Spec 2 only ever *reads* balances; it never assumes a seed. The seed is Spec 5's job.

**Strengthened enablement gate (deployment consequence):** Under the four-bucket model, `wallet` starts at 0 and the `min` account is absent until Spec 5. Spec 2's fallback would therefore find no standard buy-in funds until Spec 5 releases the weekly minimum — or the GM tops up wallet. Therefore: **Spec 2 may be implemented before Spec 5 on the unreleased branch, but the standard four-bucket economy cannot be *enabled* until Spec 5 seeds `min_reserve`, releases the current-week `min`, and establishes the buy-in postings.** Build order unchanged (1 → 2 → 3 → 5 → 4); the enablement gate tightens.

### I-2 — `min_reserve:{team}` is a new Spec 5-owned account

**Disposition:** Add `min_reserve:{team}` to Spec 5's account lifecycle as the **weekly runway** — distinct from `reserve:{team}` (championship). Hard rule: **must NOT reuse `reserve:{team}`**. Spec 2 consumes only *released* weekly `min:{team}:{week}`, never the runway directly. Recorded here so Spec 5's account topology doesn't collide with Spec 2's contract (`min:{team}:{week}`, `wallet`, `escrow:*`, `reserve`).

### I-3 — Skunk becomes a separate Opus-gated Spec 5 submodule

**Disposition:** Technically independent from wager funding and availability: assessments never debit Wallet or escrow, while the season payout credits the champion's Wallet (parallel receivable/liability ledger per R2/R3). **Definite spec home: Spec 5, as a separately reviewable submodule** — avoids an orphan finding. Rationale: commissioner-configured fee; Yahoo-derived regular-season weeks; new canonical economy accounts (`receivable:skunk:{team}:{season}`, `skunk:{league}:{season}`); season-close ordering; postseason wallet credit; off-wallet receivable reconciliation. Does not gate Specs 1 or 2; implementable independently within the Spec 5 workstream; its Opus review stays separate from the four-bucket topology review.

**Correction to the handoff:** Skunk pot maximum is **exact, not approximate**. Under R3, tied GMs split one fee and exactly one fee enters the pot each week, so `maximum pot = regular-season weeks × configured fee`. Change "max ≈ weeks × fee" to "max = weeks × fee."

### I-4 — Available to Bet: no commitment subtraction

**Disposition:** **Confirmed correct — and it validates Spec 2's escrow-at-issue design.** `Available to Bet = ledger_balance(wallet:{team}) + ledger_balance(min:{team}:{current_week})`, **no subtraction.** Spec 2 debits source accounts at ISSUE (issuer Anchor) and ACCEPTANCE (Derived) — real escrow — so committed BAB is already absent from posted wallet/min balances. Subtracting again double-counts. The old inline `ledger_cents − ch_reserved` at four sites was the soft-reservation ghost, retired with `_challenge_reserved`. Counter proposals move no money and are not commitments.

### I-5 — Championship payout placement authority

Source: `FINDING_Championship_Pot_Postseason_Basis.md` (UI/UX branch, My Ledger, 2026-07-20), grep-verified.

**Disposition:** Approved as a Spec 5 season-close finding with a **shipped-code-fix flag**.

**Issue:** The built and tested Championship Pot distribution path pays 60/30/10 using regular-season standings by default. The governing product ruling is finalized Yahoo postseason bracket placement: champion, runner-up, and official third-place finisher. The payout arithmetic is already correct and basis-agnostic; the defect is the default placement source (`stripe_connect.py:732` `_compute_standings_order()`, defaulted at `:554`, docstring `:541`; API layer `main.py:1359`; settlement report `settlement_report.py:80`).

**Scope:** Narrow code correction plus a new Yahoo data dependency:
1. Add an authoritative Yahoo postseason placement reader (none exists today — every current "playoff" hit is the simulator/projection modules, not final results).
2. Replace the default regular-season-order source with finalized playoff placement.
3. Preserve the existing 60/30/10 payout calculation and remainder handling (do NOT rewrite the payout math).
4. Amend the five conflicting protocol rules (§3 LED-344, §4 Row-6 hybrid, §4 BAB-405, §4 BAB-407, §7 CFG hybrid).
5. Add a regression test that exercises the DEFAULT path without passing an explicit order — the current suite passes `standings_order` explicitly in every case and would stay green even with the wrong default (the bug is test-masked).

**Placement authority:** First and second come from the finalized championship matchup. Third comes only from Yahoo's official third-place matchup or recorded third-place placement. The system must not infer third place from regular-season standings.

**Fail-closed rule:** If Yahoo's postseason bracket is incomplete, tied, unresolved, or provides no authoritative third-place result, Championship Pot payout remains **pending**. No payout posts and no regular-season fallback is permitted.

**Two-pots / two-axes rule:**
- Championship Pot → finalized postseason bracket placement.
- Skunk Pot → regular-season Points For champion.

The Skunk mechanic is unchanged. Do NOT touch skunk rules (§4 L291, AP-146, CFG-507, LED-345 — correctly regular-season Points For).

**Parameter rename:** rename the override from `standings_order` to `placement_order`, with temporary backward-compatible aliasing if needed, so the old regular-season meaning does not survive in the API contract.

**Code-fix flag:** Unlike I-1 through I-4, this finding corrects **shipped, tested behavior**. Implementation requires live re-grep, diff review, default-path regression coverage, and explicit implementation clearance before code changes.

**Batching:** Include in the Spec 5 season-close Opus review with the Rev 2 economy/skunk package (shared season-close path), but review as a **distinct finding** because it changes existing production behavior and adds a new Yahoo ingestion path.

**Build-thread recon:** Re-grep the live locations for the default order source, API documentation, settlement-report caller, and tests before implementation. Line references are evidence from 2026-07-20, not immutable coordinates.

### Spec 5 scope impact (recorded)

Spec 5's scope expands and sharpens from these findings: four-bucket $0-wallet economy topology (Findings 1/2, R1); `min_reserve:{team}` runway account (I-2); skunk liability submodule (I-3, R2/R3); championship payout placement-authority code fix + Yahoo bracket reader (I-5, shipped-code-fix flag); buy-in Door 1 postings that seed wallet 0 / min_reserve full / reserve per R1; the `×14` invariant rewritten to validate against Yahoo-derived week counts, not a fixed 14. Sequence as one Opus batch with the existing 5.1/5.2/pool-fee queue where topology overlaps; skunk and the I-5 championship fix each reviewed as distinct findings.

### First code-facing recon (for the build/Spec 5 thread, NOT this thread)

Re-grep live before baking Findings 1/2: confirm `economy_config.py:42-46` funds `wallet_cents` and `:61-64` enforces the `×14` assertion. Same existence-check discipline that's been burned three times on stale "current behavior" claims. Read-only; no schema or code work in the design thread.

---

## Section 7 — Pass 1 (Ledger & Account Identity) findings (2026-07-20)

Read-only audit against the approved Step 0 authority hierarchy (cleared spec text ▸ Register v12.2 ▸ approved register-incorporated source docs ▸ Merged Sections 1–8; live code/tests are evidence only, never governing). Append-only record of approved, amended Pass 1 output. No code, schema, tests, or migrations were changed. Findings are decision-scoped; line references are 2026-07-20 evidence, not immutable coordinates.

### Spec 1/2 FOUNDATION blockers (Spec 2 directly posts to or depends on)

- **P1-L2 — Off-ledger balance mutation (PROVEN LIVE paths).** `wallet_manager.deposit:141` mutates float `wallet.balance` + `Transaction` row with no `ledger_post`, reached live via `faab_wallet.init_season:330` (opening balances) and `create_bet_topup:420` (bet top-ups); `faab_wallet.transfer:656-679` mutates `wallet.balance`/`waiver_balance` floats with no `ledger_post`. Ledger `wallet:{team}` therefore diverges from the float mirror on live funding paths that Spec 2's source-split funding reads. Confirms AP-155 `[PENDING CODE-VERIFY]` ("deposit path currently writes off-ledger"). **CONFLICTS.** The commissioner-rule paths (`commissioner_rules:572,701,751,589,725`) are recorded as off-ledger, **reachability pending** — NOT folded into the proven foundational risk.
- **P1-L3B — Challenge funding decision made on float.** `beef_engine._place_beef_side:571` re-checks `wallet.balance < amount` in float, not in ledger cents. **CONFLICTS.** Spec 2's funding gate must decide from `balance_of("wallet:{team}")`. Split from P1-L3.
- **P1-L6 — Ledger lacks persistent, uniqueness-enforced protocol-event identity linked to the posting batch (SYS-007/201).** `post()` self-mints `posting_id=uuid4` (`ledger.py:294`); no external event identity is accepted or persisted; `LedgerEntry` has no event link (`ledger.py:56-66`). Only guard is balance-based (`wager_settled`+escrow-0, `:188-196`), post-commit not event-keyed. **MISSING.** Requirement stated implementation-neutral; delivery is Spec 2 §7 (an `event_id` column is one satisfying design, not the requirement itself).
- **P1-L7 — No deterministic Wallet-row lock / balance concurrency (SYS-003/204).** No `FOR UPDATE`/`with_for_update` on Wallet anywhere; `_balance_of_in_session` is a lock-free SUM (`ledger.py:89-105`). **MISSING.** Double-spend risk across simultaneous challenges. The REPEATABLE-READ post-autobegin timing (`beef_engine.py:876-877` set after first query `:791`) is noted as "may not reliably compensate; verify at build," NOT as established fact — the absent Wallet locks sustain the finding on their own.

### Spec 5 / launch blockers (out of Spec 2 scope)

- **P1-L1 — Championship account split-brain.** Bare `championship` (`shortfall_sweep.py:155,158`) vs `championship:{league_id}` (`pool_engine.py:709,732`); readers sum both (`settlement_report.py:83`, `stripe_connect.py:529`). **CONFLICTS, HIGH money-path** (cross-league commingling / non-isolated championship balance). Register B7 domain; fix before any new championship posting. (Demoted out of the Spec 1/2 foundation list: Spec 2 §0 lists Championship as out of scope; Spec 2 neither posts to nor reads these accounts.)
- **P1-L3A — Float money columns exist.** `schema.py:193,220,249,298,319,512` store BAB as Float; storage-prohibition SYS-1003. **CONFLICTS (storage) / PARTIAL (ledger `amount_cents` conforms).** Spec 5 column retirement.
- **P1-L5a — Four-bucket topology accounts MISSING.** No `min:`/`min_reserve:`/`frozen:` account strings in production postings. **MISSING.** Spec 5.
- **P1-L5b — Two-bucket buy-in seed RETIRED ASSUMPTION.** `stripe_connect.py:328-329` seeds funded `wallet:=wallet_cents` + `reserve:=reserve_cents` (superseded two-bucket model). **RETIRED ASSUMPTION.** Spec 5.

### I-5 reconfirmation (not a new finding)

- **P1-L8 — Live ledger-side re-confirmation that I-5 remains active and test-masked at HEAD.** Default `order = standings_order or _compute_standings_order(...)` (`stripe_connect.py:554`), `_compute_standings_order` pays regular-season order (`:732`); tests pass explicit `standings_order` (`test_championship_payout.py:202,227`) so the default is never exercised. Attributed to the existing I-5 shipped-code-fix tracking; no separate disposition.

### Non-blocking dispositions (recorded)

- **P1-L4 — `escrow:challenge:{id}` MISSING = Spec 2 core deliverable.** Its scope (real issuer escrow at issue, per A1), not a blocker against Spec 2. `issue_challenge` posts zero ledger today (`beef_engine.py:725-733`); escrow exists only at accept via `escrow:{bet_id}` (`:604`).
- **P1-L5c — C-1: `reserve:{team}` CONFORMS by absence.** Verified: written once at buy-in (`stripe_connect.py:329`), read-only thereafter (`:528`); no weekly-release-toward-wallet code exists anywhere. The document-level authority conflict (Merged §1.3 weekly-release semantics vs Register I-2 / handoff R1 championship-only) is resolved by hierarchy; the code never implemented the stale weekly-release semantics. Recorded as its own conforming disposition so it is not swept into the Spec 5 MISSING bucket.

### Step 0 observed conditions carried here (documentation-provenance, not code findings)

- **DP-0 — Restored source docs.** `HANDOFF_Economy_Skunk_Reconciliation_v2.md` and `FINDING_Championship_Pot_Postseason_Basis.md` were restored from `(1)` download-suffix duplicates during setup. Flagged for the future master-plan reconciliation.
- **Master-plan base absence.** `MasterPlan_v8_LaunchPath.md` is absent from the tree; non-governing and non-impairing to this audit. Flagged for the future master-plan reconciliation.

### Pass status

Pass 1 (Ledger & Account Identity) complete and recorded. Pass 2 not authorized. No remediation performed.

---

## Section 8 — Pass 2 (Wallet, Availability, Buy-in, Reserves) findings (2026-07-20)

Read-only audit against the approved Step 0 authority hierarchy (cleared spec text ▸ Register v12.2 ▸ approved register-incorporated source docs ▸ Merged Sections 1–8; live code/tests are evidence only, never governing). Append-only record of approved Pass 2 output. No code, schema, tests, or migrations were changed. Line references are 2026-07-20 evidence, not immutable coordinates.

### Terminology note (governs how these findings read)

`faab_wallet` and related FAAB-named symbols are **legacy code names for the live currency now called BAB**, following the naming sequence FAAB → BAAB → BAB. They are **not** a separate or retired currency subsystem. Every `faab_wallet` reference below is a live BAB money path.

### Spec 1/2 FOUNDATION — sharpened (no new standalone blocker; existing P1 blockers widened)

- **P2-W5 EXTENDS P1-L2.** Adds `settlement_engine:715` (single-party / non-beef settlement credit does `wallet.balance += payout` in float, with no `ledger_post` — the only `ledger_post` calls in `settlement_engine` are the beef branch at `:558`/`:604`) to the proven off-ledger mutation reach. P1-L2's divergence now spans funding **and** single-party settlement credit. Commissioner-rule paths (`commissioner_rules:572,701,751`) remain reachability-pending. **CONFLICTS.** Does not reopen P1-L2.
- **P2-W4 EXTENDS P1-L3B.** The float-based availability decision is not confined to `_place_beef_side:571`; `faab_wallet.transfer:656` gates a real BAB bet-wallet withdrawal on the float mirror (`bet_wallet.balance`), inconsistent with the beef path's ledger read (`_balance_of_in_session`, `beef_engine.py:639`). P1-L3B widens to "all funding/withdrawal availability gates must read ledger cents," now with a second proven site. **CONFLICTS.** Does not reopen P1-L3B.
- **P2-W3 (foundation-adjacent).** Available-to-Bet diverges from I-4. The beef path computes `ledger_cents − challenge_reserved` (`beef_engine.py:641,727,1017`) and omits the `+min` term. The `−challenge_reserved` retirement is Spec 2 (couples P1-L3B; `_challenge_reserved` still live at 6 sites — functional `:640,726,1016`, `faab_wallet.py:655`; display `wallet_manager.py:112`, `faab_wallet.py:218`); the `+min` is Spec 5. **CONFLICTS with I-4 end-state.**

### Spec 5 / launch blockers

- **P2-W1 — CONFLICTS.** `confirm_buyin_payment` seeds the full `wallet_cents` into the wagerable `wallet:{team}` (`stripe_connect.py:241,328`) — funded two-bucket model; protocol requires $0-wallet four-bucket (I-1, §1.3). Extends/confirms P1-L5b. Spec 5.
- **P2-W2 — CONFLICTS.** Hardcoded 14-week regular season in four sites — `economy_config.py:61` (`wallet_cents == weekly_min_cents * 14` invariant + `ECONOMY_STOPS` table), `stripe_connect.py:736` (`Matchup.week <= 14`), `pool_engine.py:705` (`week == 14` rollover). Reserve ratios coincide with R1 only at exactly 14 weeks; any non-14-week league is mis-funded. Protocol (handoff R1, AP-166) requires Yahoo-derived `season_final_week`. Spec 5 (economy) + Spec 4 (rollover).
- **P2-W6 — MISSING.** No config/season freeze (B6). `setup_pool_config` (`pool_engine.py:164-182`) and `set_league_economy_stop` (`economy_config.py:96-118`) have no time-based guard; no unspent-min destination, no `frozen:{team_id}`, no kickoff freeze. Spec 5.

### Reaffirmed

- **C-1 (P1-L5c)** reaffirmed **CONFORMS by absence** from the availability angle: no `reserve:{team}` debit anywhere; credited once at buy-in (`stripe_connect.py:329`).
- **No-double-count of real escrow CONFORMS** — the beef path drops `bet_exposure` (`beef_engine.py:633-637`).

### Named Pass 3 target (carried forward, NOT a Pass 2 finding)

- **P2-W5 adjacent observation.** Because single-party settlement never posts escrow-out (only the beef branch drains escrow at `settlement_engine:558`/`604`), single-party `escrow:{bet_id}` may never be ledger-closed. Flagged as a **Pass 3 (Escrow & Settlement) priority target**; NOT asserted as a finding this pass — Pass 3 owns verification.

### Pass status

Pass 2 (Wallet, Availability, Buy-in, Reserves) complete and recorded. Pass 3 not authorized. No remediation performed.

---

## Section 9 — Pass 3 (Escrow & Settlement) findings (2026-07-20)

Read-only audit against the approved Step 0 authority hierarchy (cleared spec text ▸ Register v12.2 ▸ approved register-incorporated source docs ▸ Merged Sections 1–8; live code/tests are evidence only, never governing). Append-only record of approved, amended Pass 3 output. No code, schema, tests, or migrations were changed. Line references are 2026-07-20 evidence, not immutable coordinates.

### Headline distinction

- **BEEF settlement foundation: CONFIRMED SOUND at HEAD.**
- **SINGLE-PARTY settlement: LAUNCH-BLOCKED pending product/funding governance.**

### CONFORMS — beef settlement foundation (reassurance for Specs 1–2)

- Beef settlement is **escrow-sourced** (reads actual `balance_of("escrow:{bet_id}")`), unequal-stakes-tolerant, closes escrow to zero, and credits the winner / refunds pushes **through the ledger** (`settlement_engine.py:557,600-608`). FR-5.9/5.10 **verified still holding at HEAD** by reading the code, not the label.
- Escrow identity `escrow:{bet_id}` at settlement is consistent.
- Post-accept cancellation correctly absent (AP-245; `Bet.status IN (pending,won,lost,push)`, `schema.py:204`).

### P3-S1 — Single-party settlement has no governed funding source for above-stake payout — LAUNCH BLOCKER

- **PRIMARY defect.** A single-party bet escrows only the bettor's own stake (`escrow:{bet.id}=amount`, `bet_engine._place_bet:144-151`) but pays `amount*odds` (`settlement_engine.py:688,702,706`). When `payout > stake`, the excess BAB has **NO identified source account.** Beef balances because it funds the payout from **TWO** escrows (winner + loser stake); single-party has **ONE**. Draining 100 to credit 200 cannot sum to zero.
- **The only possible sources:** (a) house/platform liability — CONFLICTS with no-house / no-vig (CORE-003/CORE-004/AP-301); (b) an opposing prefunded stake — which makes it a beef; (c) a separately funded pool — none exists; (d) retire. **No approved source currently exists.**
- **Confirmed code facts.** Off-ledger credit (float `wallet.balance += payout`, `:715`, no `ledger_post`); escrow-out **MISSING** (`escrow:{bet.id}` never drained in the `:679-736` branch).
- **Economic-closure vs zero-sum (precise).** The ledger remains **arithmetically zero-sum** (`trial_balance` passes because the placement posting was balanced), but the wager **fails ECONOMIC CLOSURE** — escrow strands and the payout exists only in the float mirror. Ledger zero-sum balance is NOT correct lifecycle conservation.
- **Copying the beef path is NOT a valid fix** (does not balance for a single escrow).
- **Classification.** CONFLICTS (no-house funding conflict + economic-closure break) + AUTHORITY AMBIGUOUS (should the path exist; no governed funding source). Extends P1-L2/P2-W5, couples P1-L6. **NOT a Spec 1/2 foundation item** (single-party bets are outside the challenge-escrow specs). Test-masked (`test_beef_settlement_escrow_close_pg.py` exercises only the beef branch; seeds escrow directly `:131,169`).
- **Home.** Dedicated settlement/taxonomy resolution; the funding-source ruling is a **PREREQUISITE to any settlement implementation** for this path.

### OPEN PRODUCT/PROTOCOL RULING (recorded, not decided)

Pending an explicit wager-taxonomy and payout-funding ruling, single-party non-Beef endpoints **MUST fail closed or remain disabled.** No house-funded BAB liability is permitted. This is **NOT remediation authorization** and does not choose among: retirement / conversion to a two-party challenge / a separately funded pool / another explicitly governed non-house structure.

### P3-S2 — Once-only settlement guard is balance-keyed with asymmetric coverage — couples P1-L6; does not reopen it

- Only idempotency mechanisms: FR-8.7 week-claim (week-scoped, `settlement_engine.py:746-778`), balance-based `wager_settled`+escrow-0 guard (beef only, `ledger.py:188-196`), `bet.status` re-select filter. No event-keyed guard; single-party has no ledger-level guard.
- **Scope split (three homes):** Spec 2 owns event identity for challenge/beef settlement; the ledger-event primitive (P1-L6) may be **SHARED** infrastructure keyed by many; single-party idempotency belongs with the **P3-S1 settlement/taxonomy resolution, NOT Spec 2.** Single-party may be failed-closed/retired before any idempotency is required. **PARTIAL.**

### P3-S3 — Settlement serialization narrows P1-L7 (note, relief)

- Settlement serializes via `SELECT … FOR UPDATE` on `week_settlements` (`settlement_engine.py:435-442`). The P1-L7 no-lock gap is specific to **ISSUE/ACCEPT**, not settlement. **CONFORMS at the settlement moment.**

### Foundation-blocker status

Pass 3 surfaced **NO new Spec 1/2 foundation blocker.** Foundation set unchanged (**P1-L2, P1-L3B, P1-L6, P1-L7**); P3-S1 is a **launch blocker outside Spec 1/2 scope.**

### Pass status

Pass 3 (Escrow & Settlement) complete and recorded. Pass 4 not authorized. No remediation performed.
