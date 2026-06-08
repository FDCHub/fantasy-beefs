# Fantasy Beefs — Decision Engine Roadmap

> Location: `fantasy-beefs/tools/`
> Created: June 7, 2026
> Status: Design locked. Rev 1 ready to build.
> Owner: Fraser (Flavor Frase) · Commissioner & Developer

---

## The Thesis (one sentence)

**Evaluate roster states, not players.** Build a future roster, run it through a
season-long simulation, and rank moves by how much they improve championship odds.

A trade is a roster change. A waiver add is a roster change. "Do nothing" is the null
roster change. One engine answers all of them — only the input differs. This is what
prevents doubled effort: we do not build a trade tool *and* a waiver tool *and* a
scenario tool. We build one roster-state evaluator and point it at different inputs.

This roadmap adapts the GM Engine concept docs (overview + Appendix 2) to the Fantasy
Beefs stack. The freemium/monetization apparatus (Appendix 1) is explicitly dropped —
this is a real tool for the league, not a market product.

---

## What Already Exists vs. What Is New

This is the single most important section for scoping. The corrected picture:

**EXISTS (P0 Module 6, built + verified on 17 weeks of mock data):**
A *single-week, two-lineup* Monte Carlo. It takes two GMs' projected starting-lineup
totals, runs ~10,000 sims with projection + variance, and returns a win probability
between those two lineups (converted to betting odds). This powers the Odds Calculator
and the betting board.

**DOES NOT EXIST:**
A *multi-week, whole-season* simulator that takes an arbitrary hypothetical roster,
re-optimizes its weekly lineups, and projects it forward across the full schedule into
playoff and championship odds. This is the GM Engine's "judge of roster states." It was
never built because betting only ever needed this week's two lineups.

**The relationship:** the existing per-week head-to-head sim is a *reusable component*
of the season-long machine. We wrap it in a week loop and a roster-state layer. We do
not rebuild it.

**Also reusable from prior phases:**
- Yahoo ingestion (being stood up now via OAuth)
- FantasyPros projections (already in DB schema, P0 Module 3)
- `NormalizedLeague` / `NormalizedRoster` / `NormalizedMatchup` models (P0) — the
  source-of-truth shapes that make mock→live swapping safe
- Mock league: 17-week seeded, deterministic, verified

---

## Architectural Spine (applies to all revs)

```
   Data Provider (swappable)          ← Mock now, Yahoo later. Same interface.
        │  emits NormalizedLeague / Roster / Matchup
        ▼
   Roster-State Engine (NEW)          ← Builds current + hypothetical future states
        │  emits RosterState objects
        ▼
   Season Simulator (NEW wrapper)     ← Week loop over the EXISTING per-week sim
        │  emits playoff odds, championship odds, per-week win-prob
        ▼
   Decision Layer (NEW)               ← Diffs states, ranks by Decision Value
        │
        ▼
   Heat Map / Views (NEW)             ← Three-horizon display
```

**Hard rule — the data-provider seam.** The engine reads *normalized models*, never
Yahoo directly. A mock provider serves them now; a Yahoo provider serves them later.
The engine never knows which. Swapping data sources = swapping one provider. This seam
is what lets dev start before OAuth is finished.

**Hard rule — the simulator is the only judge.** No view or tool computes its own
verdict. Everything builds a roster state and asks the simulator. One source of truth
for "is this good," mirroring how `odds_engine.py` is the one source of truth for
betting math.

**Hard rule — every feature is the same verb:** build a state, sim it, diff it. If a
proposed feature cannot be expressed that way, it does not belong in the engine.

---

## The Three Revs

### Rev 1 — Team Health (≈2–3 weeks)

**Goal:** Prove the thesis end to end. Read the real (or mock) roster + schedule, run
the existing per-week sim across the *remaining schedule* — your optimized lineup vs.
each scheduled opponent's optimized lineup, week by week — and render the three-horizon
heat map.

**Evaluates the team AS IT STANDS. No hypotheticals yet.** Answers: where am I strong
and weak, and when. This is the diagnostic layer that tells later revs what problems to
solve.

**Three horizons:**
- **This Week** — real scheduled opponent, optimized both sides. Sharp.
- **Rest of Season** — real remaining schedule, each real opponent. Confidence widens
  with roster drift.
- **Playoffs** — playoff weeks (from league settings). Opponent model is the one open
  decision (see below). NFL playoff-week schedule is a cheap signal regardless.

**Heat-map cell:** win-probability delta = color; projected point swing = number.
Near-term sharp, far-term blurry, sharpens weekly. This blur is honest — inputs
genuinely settle over time — not a retention gimmick.

**Reuse:** per-week Monte Carlo (P0 M6), FantasyPros projections (P0 M3), normalized
models (P0), mock league.
**New:** data-provider seam, week-loop wrapper, lineup optimizer, heat-map view.

**Why 2–3 weeks holds here only:** the hard sim already exists. We schedule it across a
season; we do not invent it. This is the *only* rev where the Odds-Calculator-like
2–3 week feel applies — Revs 2 and 3 carry more new logic.

---

### Rev 2 — Roster-State Evaluation (≈3–4 weeks)

**Goal:** Deliver the thesis. Add the hypothetical. Build the Roster-State Engine: take
one candidate move (waiver add / trade / drop / hold), construct the future roster,
re-optimize its weekly lineups, re-run Rev 1's season sim, and show the heat map
**before vs. after**.

This is **The War Room** (private, your side only) and a first cut of **Decision
Value** — the championship-odds delta from the move.

Several roster-management factors start being reasoned about here because they fall out
of honestly-built before/after states: forced-drop cost, open-slot value, bye-week
economics. (A factor is only "handled" when the state carries the field AND the engine
generates the candidate state AND the sim weighs it. See factor table below.)

**Longer than Rev 1 because:** roster-state construction + weekly lineup re-optimization
is the genuinely new module the docs center on. Backend + Railway + real-data failure
modes also enter here.

---

### Rev 3 — Decision Surface + Remaining Factors (≈3–4 weeks)

**Goal:** Most of the docs. Multiple candidate moves ranked in one list — the "unified
solution marketplace," where an $11 waiver add and a two-player trade sit side by side,
ranked by Decision Value (championship-odds gain ÷ resources consumed). Waiver-vs-trade
comparison. **The Sit-Down** (public, limited) with **Cooperating** (the rat layer —
a GM sacrificing his own team to help another win).

Plus the explicit-logic factors that do NOT fall out of the sim and need their own
reasoning: opponent blocking, market context, timing / multi-step planning.

---

## Roster-Management Factors — Mapping to Homes

The docs (overview §8) are explicit: these are NOT a user-facing checklist. The user
never selects a factor. The engine reasons about them silently and bakes them into
every recommendation.

A factor is only handled when ALL its layers are present: the state carries the field,
the engine generates the relevant candidate state, the projection layer carries the
needed distribution, and/or explicit logic exists. "Data is in the state" ≠ "factor is
reasoned about."

| Factor | Primary Home | First Rev |
|---|---|---|
| Forced-drop cost | State + sim (dropped player gone from future weeks) | Rev 2 |
| Open roster slot value | State + candidate-state generation | Rev 2 |
| Bye-week economics (take-a-zero vs. hold) | Candidate-state generation + sim | Rev 2 |
| Bench compression / depth | State + sim | Rev 2 |
| Positional depth | State + sim | Rev 1 (diagnostic) / Rev 2 |
| Future weakness detection | Season sim across schedule | Rev 1 |
| Playoff schedule awareness | Playoff-horizon sim | Rev 1 |
| Standings context (lead = safe, behind = upside) | Reading of odds distribution | Rev 2 |
| Roster flexibility | Candidate-state generation | Rev 2 |
| Injury exposure / resilience | Projection layer (distributions) | Rev 2 |
| Player volatility | Projection layer (range-of-outcomes) | Rev 2 |
| Correlated risk (shared bye/offense/injury) | Projection layer + explicit logic | Rev 3 |
| Decision Value (gain ÷ resource) | Decision layer | Rev 2 (cut) / Rev 3 (full) |
| Waiver vs. trade comparison | Decision layer (unified ranking) | Rev 3 |
| Opportunity cost / transaction scarcity | Decision layer + explicit logic | Rev 3 |
| Stash value | Candidate-state generation + playoff sim | Rev 3 |
| Multi-step planning / timing | Explicit logic (sequence of states) | Rev 3 |
| Opponent blocking | Explicit logic (league digital twin) | Rev 3 |
| Market context | Explicit logic + external data | Rev 3 |
| Hidden consequences | Emergent from honest state + sim | Rev 2–3 |

**Takeaway:** the list reads like a 20-item backlog. It is really a 3-item backlog —
honest state, good projections, season sim — plus a handful of explicit-logic features
for Rev 3. Build the spine right and ~15 factors are expressed by the machine itself.

---

## The One Open Decision

**Playoff-horizon opponent model.** The schedule lookup runs out at the playoff line —
the bracket does not exist yet (seeding depends on results, including the moves being
evaluated). Two forks:

- **Generic elite opponent** — sim playoff weeks vs. a top-tier average lineup. Simple,
  stable, slightly pessimistic, always available, no seeding needed.
- **Weighted field** — sim vs. likely playoff teams weighted by current playoff odds.
  Sharper, honestly blurry early, needs a playoff-odds sim underneath.

Not blocking for Rev 1 (which can ship with the generic model and upgrade later).
**Decision deferred to Fraser.**

---

## Dev Workflow — Doubling Effort with Claude Code + Qwen

The MODULE_SPEC is what enables parallelism. A tight spec turns most work into
Qwen-sized tasks; the vague joins go to Claude Code.

- **Qwen 2.5-Coder (coder-node, 10.0.0.11):** well-specified single-file work — the
  heat-map render, individual sim loops, FastAPI route bodies, the mock provider's
  data methods. Strong when the spec is tight; weak on ambiguity and multi-file glue.
- **Claude Code (CLI in PyCharm):** multi-file architecture and load-bearing joins —
  the data-provider interface, the Roster-State Engine wiring, integration debugging.

**Rule of thumb:** the *seam* is Claude Code's job; the *modules behind the seam* are
Qwen-able. Each Rev spec marks every task `[QWEN]` or `[CLAUDE-CODE]`.

---

## Sequencing & Gates

- **Mock-first.** Dev builds against the deterministic mock provider now. OAuth proceeds
  in parallel. Rev 1 ends by swapping the mock provider for the Yahoo provider behind
  the same interface. Real value arrives at the *end* of Rev 1, not blocked at the start.
- **Railway** remains the prerequisite for any remote-GM-accessible tool (Rev 2+).
- **Rev 2 and Rev 3 specs are written AFTER Rev 1 is built** — speccing them now would be
  guessing; Rev 1's reality will reshape them.

---

*Fantasy Beefs — Decision Engine Roadmap · June 7, 2026*
*Our Thing. Your League.*
