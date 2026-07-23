# Launch Gate Audit Protocol — Fantasy Beefs MVP

**Purpose:** A necessary-and-sufficient review of the DRAFT Launch Gate in `FantasyBeefs_MasterPlan_BAB_Reconciled_v4.md` — nothing else. This is not a review of the whole plan, not a review of the code, and not a re-run of the Plan Audit Protocol. It has one target: the seven-line DRAFT Launch Gate in Part 1, and the one question of whether that gate is the right finish line for an August 1 real-money launch.

**Why this exists:** The Launch Gate was drafted from what the Master Plan *implies* is load-bearing. Every line is marked as inference. A gate drawn from inside the plan can only be as complete as the plan it was drawn from — if the plan silently omits a required capability, the gate omits it too. That blind spot is the whole reason for a separate, adversarial pass. The person building this has stated plainly that they do not yet trust their own judgment on whether the gate captures the necessary and sufficient items. This audit exists to find the missing necessary item before launch day finds it for them.

**The two failure modes this audit hunts:**
1. **Under-inclusion (the dangerous one):** a capability that is genuinely required for a real-money MVP to function, or to be safe, that the gate does not list. A launch that ships without it is broken or unsafe on day one.
2. **Over-inclusion (the wasteful one):** a capability on the gate that is *not* actually required for launch and could be fast-follow — every one of these that stays on the gate is a task falsely made launch-blocking, eating the thin runway.

---

## Ground rules (same discipline as the Plan Audit and Math Review Protocols)

- **Findings only. No fixes, no rewritten gate, no code.** Each finding is reported, not resolved, in this pass.
- **Each finding has four parts:** Location (which gate line, or "missing — no line"), Plain English (what's wrong or missing), Why it matters (what breaks at launch if this goes unaddressed), Correct approach (the shape of the fix — not the fix itself).
- **Fraser reviews and approves each finding individually** before anything in the gate changes.
- **Cite the gate's own words.** Quote the actual line being flagged. For a missing capability, name it plainly and say where in the flow it would sit.
- **Distinguish "I lack context" from "genuinely absent."** If a capability isn't in the gate and isn't obviously covered elsewhere in the plan, that's a real finding. If it's just unfamiliar, say so honestly rather than treating unfamiliarity as a gap.
- **Real-money bar.** This is a real-money peer-to-peer wagering product, even if the money is a private $200 season buy-in among twelve people who know each other. Judge the gate against the standard of "money moves correctly and safely between real people," not "a demo works." A wrong settlement, a double-spend, a bet that locks at the wrong time, or a wallet that can go negative is a launch-blocker even in a friendly league.

---

## The current DRAFT Launch Gate (the object under audit)

Reproduced here so the audit is self-contained. This is the gate exactly as it stands in v4. A GM can do the following, end-to-end, against real BAB wallet balances, or the product does not launch:

1. **Fund BAB.** The $200 buy-in exists as a wallet balance ($140 visible / $60 reserved).
2. **See their wallet.** Single BAB balance with the visible/reserved split rendered.
3. **Place at least one versus bet end-to-end.** Offer → accept (Beef accept flow) → lock → settle, against real balances.
4. **Place at least one pool bet end-to-end.** Pick → lock at Thursday kickoff → settle.
5. **The week locks correctly.** `_nfl_lock_time()` returns the right kickoff; `per_bet_lock.py` placeholder fix shipped.
6. **Settlement moves real money correctly.** No invented money, penny-exact splits, fail-loud on missing wallets.
7. **The reserve-ceiling holds.** A GM cannot wager beyond the ceiling.

Everything not on this list is declared fast-follow.

---

## The specific questions to answer

Work through these in order. Each should produce zero or more findings, in the four-part format above.

### 1. Is each line on the gate actually necessary?

Take each of the seven lines in turn. For each, ask: if this capability were missing at launch, would the product be broken, unsafe, or unable to complete a real-money bet? If the honest answer is "no — it would be degraded but still function and still settle money correctly," that line is a candidate for fast-follow, not the gate. Over-inclusion wastes the runway. Name any line you believe is not truly launch-blocking, and say what makes it survivable to defer.

### 2. What necessary capability is missing entirely?

This is the sharpest question and where the audit earns its keep. The gate lists seven capabilities. A functioning real-money wagering MVP may need more that nobody wrote down. Think through the full lifecycle of a real bet and a real season, and name anything required-but-absent. Prompts to force the thinking (not an exhaustive list, and not all necessarily gaps — check each):
- **Identity and access.** Can a GM actually log in as themselves at launch? The plan notes `GM_TEAM_ID` is resolved via a dev-stub token and calls a real login flow "future work." Is a real login a launch requirement, or can the twelve-person league launch on stubbed identity? If stubbed identity ships, can GM A place a bet *as* GM B?
- **Wallet integrity under failure.** Can a wallet go negative? Can the same bet be accepted twice, or settled twice? The plan records a "run-once race" fix on `settle_week()` and a `BeefStarter` uniqueness fix — are the equivalent protections present on the acceptance and wallet-debit paths, and should the gate assert them?
- **The counter-offer path.** The versus-bet line names offer → accept, but the locked bet rules allow one counter. Is "a GM can counter a bet" part of the necessary versus-bet flow, or genuinely deferrable?
- **Non-participant handling.** The plan carries a locked three-way Commish setting (Pay and Forfeit / Auto-Pick / Lock Out) for GMs who don't act. If a pool bet locks Thursday and a GM never picked, does settlement have a defined, correct behavior at launch — or does an un-picked GM break settlement? Is this a gate item?
- **Commissioner setup.** Can the league actually be configured for the 2026 season before anyone bets — buy-ins recorded, settings locked? The plan hardcodes `league_id = 1`. Is any commissioner action a launch prerequisite?
- **The reserve-ceiling reality.** Gate line 7 asserts the ceiling holds, but the plan flags the ceiling *formula* as unwritten and unscoped. Is line 7 therefore currently un-satisfiable — and does that make the formula itself a launch-blocker that the gate names as done-in-principle but is actually not built?
- **Money-out at season end.** The gate covers placing and settling weekly bets. Does the MVP need the season-end ledger / reconciliation to be correct at launch, or is that safely months away and legitimately fast-follow?
- **Data freshness.** Bets settle on scores and lineups. Is there a launch requirement that the app reliably pull correct weekly scores and rosters, or is that assumed handled? What happens to settlement if the data sync fails on a Sunday?

For each prompt above, produce a finding only if it names a genuine gap or a genuine over-inclusion. If a prompt turns out to be already covered or genuinely deferrable, say so briefly and move on — do not manufacture a finding.

### 3. Is the gate's "end-to-end, against real balances" claim actually testable?

The gate repeats "end-to-end, against real BAB wallet balances." For the gate to be a finish line, someone has to be able to stand at launch and say "yes, this is true" or "no, it isn't." Ask: is each line stated concretely enough to be *checked*, or is it aspirational? A line like "settlement moves real money correctly" is only a usable gate item if there's a defined way to confirm it — a test, a query, a manual walk-through. Flag any line that cannot be objectively confirmed as done, because an unfalsifiable gate line is not a finish line, it's a hope.

### 4. Does the gate's ordering hide a dependency?

The seven lines imply an order (fund → see → bet → settle). Trace it. Does any line depend on something not yet built that an earlier line assumes? The clearest candidate: line 3 (place a versus bet) requires the Beef accept flow, which the plan says "doesn't exist at all," and line 7 (reserve-ceiling holds) requires a formula the plan says is unwritten. Flag any gate line whose satisfaction silently depends on flagged-unbuilt or flagged-unscoped work elsewhere in the plan — because that line is not "a check you'll pass," it's "a build you haven't finished," and the gate should not present the two as the same.

### 5. What is the minimum honest gate?

Given everything found above, propose — as a findings-level recommendation, not a rewrite — what the necessary-and-sufficient gate should contain: which of the current seven lines stay, which move to fast-follow, and which missing capabilities must be added. This is a recommendation for Fraser to rule on, one line at a time, not a redrafted gate. The goal is a gate that is *tight* (nothing on it that could be deferred) and *complete* (nothing missing that a real-money launch requires).

---

## What NOT to do in this pass

- Do not review the rest of the Master Plan. Only the Launch Gate. If something outside the gate looks wrong, note it in one line at the very end as an aside, but do not spend the pass on it.
- Do not judge the product decisions themselves (BAB, the bet roster, the escrow mechanic, the lock model). Those are settled. This audit is about whether the *gate* correctly captures what must ship, not whether what must ship is a good idea.
- Do not propose code fixes or write specs. That is a separate, later step.
- Do not soften a finding to be polite. A missing launch-blocker is a missing launch-blocker. Name it plainly. Under-inclusion is the dangerous failure mode — err toward flagging a possible gap rather than assuming it is covered.

---

## How to use this

Open a fresh Opus thread. Paste in this protocol and the full `FantasyBeefs_MasterPlan_BAB_Reconciled_v4.md` (the whole document, so the gate's inferences can be checked against the plan they were drawn from). Ask Opus to work through the five questions above, in order, producing numbered findings in the four-part format. Bring the findings back to Fraser for review, one at a time — same cadence as the Plan Audit and every code review. The output that matters is Question 5's minimum honest gate, built from the findings Fraser approves.
