# Fantasy Beefs — New Thread Handoff: Decision Engine Dev

> Created: June 7, 2026
> Purpose: Load a fresh dev thread (clean context) to BUILD Rev 1.
> This thread = design/specs. New thread = development.

---

## Start here

Read these two, in order, before writing code:
1. `DECISION_ENGINE_ROADMAP.md` — the why, the three revs, what exists vs. new.
2. `P3_1_REV1_MODULE_SPEC.md` — the what, file by file, with `[QWEN]`/`[CLAUDE-CODE]` tags.

Both live in `fantasy-beefs/tools/`.

---

## One-paragraph context

We are building a fantasy decision engine: evaluate roster *states*, not players. Rev 1
("Team Health") reads a roster + schedule and runs the EXISTING per-week Monte Carlo
(P0 Module 6) across the remaining schedule to produce a three-horizon heat map (This
Week / Rest of Season / Playoffs). No hypotheticals in Rev 1. The GM Engine concept
docs inspired this; the freemium/monetization parts are dropped. Fairy Goodfellas
characters are an OPTIONAL presentation skin applied last — the engine is
character-blind and must stand on its own.

---

## The five decisions that are LOCKED

1. **Mock-first.** Build against the deterministic 17-week mock league now. OAuth runs
   in parallel. Swap to Yahoo behind the data-provider seam at the end of Rev 1.
2. **The per-week sim already exists** (P0 M6: two lineups → win prob). REUSE it. The
   season-long, whole-roster, playoff/championship simulator does NOT exist — that is
   what we wrap around the per-week sim. Do not rebuild the per-week sim.
3. **Data-provider seam is mandatory.** Engine reads normalized models only
   (`NormalizedLeague`/`NormalizedRoster`/`NormalizedMatchup` from P0). Mock and Yahoo
   providers emit identical shapes. Swap = one line.
4. **ProjectionEngine converts raw → points.** The provider returns RAW FantasyPros
   production stats. A dedicated `engine/projection_engine.py` applies the league's
   scoring rules to produce fantasy points. Scoring is LEAGUE logic, not source logic —
   one path, shared by both leagues (10-GM and 12-GM may score differently) and every
   future data source. Never put scoring inside providers.
5. **Heat-map cell:** win-prob delta = color, point margin = number, confidence = blur.
   Near-term sharp, far-term blurry (honest: inputs settle over time).
6. **Design system:** Playbook light parchment theme (NOT the dark Odds Calculator
   theme). Single self-contained HTML, mobile-first, 480px.
7. **No LLM chat window in Rev 1.** The conversational assistant (The Brain answering
   team questions) is Rev 3 — it needs moves + Decision Value to reason over, which
   don't exist until Rev 2. Optional Rev 1 stretch: a single static AI summary paragraph
   (no back-and-forth), forward-compatible with the Rev 3 inference path.

---

## The one OPEN decision (Fraser to resolve; not blocking Rev 1)

Playoff-horizon opponent model: **generic elite opponent** (Rev 1 default, stable) vs.
**weighted field by playoff odds** (sharper, needs playoff-odds sim, later). Rev 1 ships
with generic; upgrade path preserved.

---

## Dev division of labor

- `[CLAUDE-CODE]` — the seam (`data/provider.py`) and the sim wrapper
  (`engine/season_sim.py`). Multi-file joins, the load-bearing glue.
- `[QWEN]` (coder-node 10.0.0.11) — lineup optimizer, team-health assembly, API routes,
  heat-map HTML. Single-file, well-specified. Can run in parallel once the seam exists.

Build order is in the Rev 1 spec, §"Build Order."

---

## Do NOT do in Rev 1

Trades, waivers, candidate moves, Decision Value, before/after diffs, War Room,
Sit-Down, Cooperating, and the LLM conversational chat window. All Rev 2/Rev 3. (A
single static AI summary paragraph is an allowed Rev 1 stretch — but NOT an interactive
chat.) Rev 2 and Rev 3 specs are written AFTER Rev 1 is built — its reality will
reshape them.

---

## Gate

OAuth flowing is NOT required to start (mock-first). Railway IS required before any
remote-GM-accessible tool (Rev 2+), not for Rev 1 local dev.

---

*Hand this file to the new thread first. Then the roadmap, then the Rev 1 spec.*
