# Opus Plan Audit Protocol — Fantasy Beefs Master Plan

**Purpose:** A structural and logical review of the Master Plan document itself — not code, not math. This is a sibling to the existing Opus Math Review Protocol, not a replacement. The Math Review Protocol checks formulas and money-path code for correctness. This protocol checks the *plan* for clarity, logical flow, hidden assumptions, and unverified claims.

**Why this exists:** across several sessions, this document has stamped claims like "confirmed," "mechanical," and specific time estimates onto tasks that were never actually checked against the live system. Three concrete examples, all discovered by directly checking rather than trusting the label: a Dockerfile that was said to bake a password into the build — it doesn't exist. A RosterSlot backfill labeled "180 rows, mechanical" in three separate places — every one of the 180 rows had a NULL value the backfill couldn't use. A caller count stated as nine in one handoff — the real count was six. None of these were dishonest. They were confident-sounding conclusions written down before anyone verified them, and each cost real time to unwind later. This audit exists to find the *next* one of these before it costs a session.

---

## Ground rules (same discipline as the Math Review Protocol)

- **Findings only. No fixes, no rewritten sections, no code.** Each finding is reported, not resolved, in this pass.
- **Each finding has four parts:** Location (where in the document), Plain English (what's actually wrong or unclear), Why it matters (what breaks if this goes unaddressed), Correct approach (what would need to happen to resolve it — not the fix itself, the shape of the fix).
- **Fraser reviews and approves each finding individually** before anything in the document changes.
- **Cite the document's own words.** A finding that says "this section is vague" without quoting the vague part is not useful. Quote the actual sentence or table row being flagged.
- **Distinguish "unclear to me because I lack context" from "actually undefined in the document."** If a term or dependency isn't explained anywhere in the document and isn't obvious from context, that's a real finding. If it's just unfamiliar, say so honestly rather than treating unfamiliarity as a flaw in the plan.

---

## The specific questions to answer

Work through these in order. Each should produce zero or more findings, in the four-part format above.

### 1. What does this document actually say we're delivering?

Read Part 1 (Backend, Frontend, Middleware) as if you were meeting this project for the first time. Write a plain-English, one-paragraph summary of what "MVP" means according to this document alone — not what you'd assume a fantasy football betting app should do, only what this specific document commits to. If you can't write that paragraph cleanly from the document's own content, that's a finding: the document doesn't actually state its own scope clearly enough to summarize.

### 2. Does it flow logically?

Trace the stated dependencies. Does Backend's "Remaining" section ever depend on something listed as still-incomplete in "In process," without saying so? Does Appendix A's estimate table match what Part 1 actually says is left to build, or have the two drifted apart? Flag any place where reading the document in order produces a contradiction, or where a "Remaining" item quietly assumes something from a different section is already done when it may not be.

### 3. What remains unclear or undefined?

Hunt for terms, thresholds, and mechanisms that are used but never defined. Examples of the kind of gap to look for (not an exhaustive list): a "reserve-formula ceiling" is referenced repeatedly as replacing `MAX_BET_PCT`, but is the actual formula written down anywhere in this document, or only promised as future work? Is "session" ever defined as a unit (hours? a sitting? a calendar day?), given that estimates are given in sessions throughout? Where a decision is marked "confirmed" or "locked," is the actual mechanism of that confirmation traceable — a query result, a quoted decision, a commit hash — or is it asserted without a visible source?

### 4. What traps remain uncovered?

This is the sharpest question. A "trap" here means: a task currently labeled small, mechanical, or low-risk that likely hides a larger dependency, the same way RosterSlot and the Dockerfile did. Look specifically at every item marked "half session," "mechanical," "small," or "low-risk" in Part 1 and both estimate tables in Appendix A. For each one, ask: has anything in this document, or anything checkable, actually confirmed this is as small as labeled — or is the label inherited from an earlier, unverified pass? Name every item where you cannot find evidence the label was checked.

### 5. How would you restructure the remaining workflow?

Given everything found above, propose a re-sequencing — not a rewrite of the plan's content, but an ordering. Should any items move earlier because they're more likely to reveal hidden scope (per the RosterSlot lesson — checking early is cheap, discovering late is expensive)? Should any "half session" items be split into "verify first, half session" and "build, unknown session count until verified"? This is a findings-level recommendation, not a rebuild of the document — Fraser makes the actual sequencing call.

---

## What NOT to do in this pass

- Do not judge whether the product decisions themselves are good ideas (BAB, the escrow mechanic, the bet roster). Those are settled; this audit is about the plan's clarity and hidden risk, not its product judgment.
- Do not propose code fixes or write specs. That's a separate, later step, same as the Math Review Protocol.
- Do not soften a finding to be polite. A vague section is a vague section; name it plainly.

---

## How to use this

Paste the full current Master Plan document into a fresh Opus thread along with this protocol. Ask Opus to work through the five questions above, in order, producing numbered findings in the four-part format. Bring the findings back here for Fraser's review, one at a time — same cadence as every code review this session.
