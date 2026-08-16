# FantasyStakes Market Line Methodology — Owner Ruling

**Status:** Adopted · **Date:** 2026-08-16 · **Implemented by:** WP3C.2

**Scope.** This ruling fills the one gap the WP3C.2 reconciliation found: how the
offered Versus spread and total are assigned. It supersedes no existing certified
settlement, Ledger, or wager-model semantics.

---

## Why this record exists

The WP3C.2 reconciliation stopped before implementation because line generation
was not governed anywhere. The engine could **price and settle** a spread or a
total given a line — `GE-621`/`GE-622`/`GE-623` and `GE-631`/`GE-632`/`GE-633` in
`spec/FantasyBeefs_Merged_Section_2_GameEngine.md` define both — but nothing in
the codebase, the specifications, the Rev 4.3 POR, or the provider produced one.
Every `line` in the system was a pass-through of a client-supplied value.

The only near-miss was a formula in `fantasy_beefs_playbook_rev1.html` §A.5,
under "The Odds Calculator". It was ruled non-governing: a member-facing creative
document under the superseded *Fantasy Beefs* brand, referenced by no
specification, implemented nowhere, ambiguous about its own inputs, and stating a
goal (`~50/50`) that its formula does not achieve against this engine's Monte
Carlo pricing.

---

## The ruling

### Moneyline

Unchanged. Odds remain derived from simulated win probabilities.

### Spread

- The offered spread is the **median of the simulated score-margin
  distribution**.
- Rounded to the **nearest 0.5** fantasy point.
- **Whole-number lines are permitted.** No half-point hook.
- Existing push semantics remain valid.
- Sign convention is standard sportsbook: **favourite negative, underdog
  positive**.
- The backend-generated signed line is authoritative.

### Over / Under

- The offered total is the **median of the simulated combined-score
  distribution**.
- Rounded to the **nearest 0.5**. Whole-number totals permitted. No hook.
- Existing push semantics remain valid.
- The total is authoritative. **The GM chooses OVER or UNDER.**

### Authoritative line rule

The same backend-generated line governs the Play card, the composer, the quote,
write-time validation, the persisted proposal terms, and settlement. The frontend
may display the line and collect legitimate user choice. It may not generate,
modify, infer, or re-price it.

---

## How it is implemented

| Concern | Location |
|---|---|
| Median, rounding, sign translation | `odds/market_lines.py` |
| One simulation → all three markets | `beefs/beef_engine.compute_market_board` |
| Served board | `GET /league/{id}/versus/board` |
| Quote-time derivation and validation | `POST /league/{id}/versus/quote` |
| Write-time derivation and validation | `POST /beef/challenge` |
| Certification | `test_wp3c2_versus_market_lines.py` |

### The sign reconciliation

Two signed numbers exist and they are negations of one another:

1. **The canonical pricing threshold** — what the engine has always meant by
   `line`. `p_anchor = P((anchor − opposite) > line)`, graded by
   `settlement_engine._eval_spread` as `margin > line` with equality a push, and
   persisted on `BeefChallenge.line`, `BeefProposal.line` and `Bet.line`. **This
   is unchanged by WP3C.2** — no schema change, no settlement change, no
   reinterpretation of existing rows.

2. **The sportsbook display line** — what a GM reads. Favourite negative.
   `display = −canonical`, performed exactly once, on the server, in
   `market_lines.sportsbook_spread`.

Storing the sportsbook number instead would have inverted the grading of every
spread wager and required changing certified settlement code. Exposing the
translation alongside the unchanged threshold is the smallest architecture that
satisfies the ruling.

### The hook question, decided

Adopting a `floor(x) + 0.5` hook would make `GE-622` and `GE-632` push outcomes
structurally unreachable. The owner ruled the hook out and push in, so
`round_to_nearest_half` rounds to the nearest half and lets whole numbers stand.
`test_wp3c2_versus_market_lines.py` §9 certifies a push through the governed
evaluator on both markets.
