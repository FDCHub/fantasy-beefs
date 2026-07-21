# FINDING — Championship Pot pays by REGULAR-SEASON standings in BUILT CODE; ruling is POSTSEASON bracket

**From:** UI/UX feature branch (My Ledger, 2026-07-20).
**To:** Main development line → money-path thread.
**Status:** RULED by product owner 2026-07-20. **Spec AND code both wrong.** Distribution path is BUILT, tested, and keyed to the wrong basis — grep-confirmed.
**Type:** Money-path. Determines who receives real BAB at season close. Opus-gated.

---

## Issue
Championship Pot pays 60/30/10 to 1st/2nd/3rd. Product-owner ruling: by **postseason (playoff) bracket finish** — actual league champion / runner-up / third-place-game winner. Spec and code both key it to **regular-season standings**, which is routinely a different set of teams.

**Correction to a prior assumption:** an earlier version of this finding guessed "no distribution code exists yet." **That was wrong.** The grep (2026-07-20) proves the distribution path is fully built and tested. This is spec + code, not spec-only.

## Skunk collision this resolves (unchanged from prior version)
- **Championship Pot → postseason bracket 1st/2nd/3rd (CHANGE).**
- **Skunk Pot → regular-season points champion (UNCHANGED).**
Two pots, two axes, two usually-different recipients.

## CODE — confirmed broken (grep 2026-07-20)
| Site | Evidence | Problem |
|---|---|---|
| `payments/stripe_connect.py:541` | docstring: order "derived from **regular-season standings (weeks 1-14)**" | Wrong basis, explicit |
| `payments/stripe_connect.py:732` `_compute_standings_order()` | computes payout order from regular-season W/L | **The source of the wrong default** |
| `payments/stripe_connect.py:554` | `order = standings_order or _compute_standings_order(...)` | Default path uses regular-season |
| `payments/stripe_connect.py:56` | `DEFAULT_PAYOUT_SPLIT = [60, 30, 10]` | Split correct; basis is the issue |
| `api/main.py:1359` | field doc: "If omitted, computed from **regular-season record**" | Same wrong default at API layer |
| `reports/settlement_report.py:80` | reuses `_compute_standings_order` default | Inherits wrong basis |
| `test_championship_payout.py` | passes `standings_order` **explicitly** in every case | **Test masks the bug** — never exercises the wrong default |

**Key nuance — the fix is narrow.** `preview_payouts()` / `execute_payouts()` ACCEPT a `standings_order` param and are basis-agnostic — feed them any ordered list and they pay correctly (60/30/10 + 5.2-3 remainder-to-1st, already built and tested). The bug lives ONLY in the **default** when no order is passed: `_compute_standings_order()` returns regular-season order. **Fix = change what the default computes, from regular-season W/L to postseason bracket placement.** Do NOT rewrite the payout math.

## DATA — the missing reader (grep 2026-07-20)
There is **NO postseason bracket result reader** in the codebase. Every "playoff" hit is the *simulator* (`season_sim.py`, `team_health.py`, `playoff_prob`, `war_room_routes`) — projections, not final results. `_compute_standings` (`api/main.py:339`) computes regular-season W/L only. **The data the fix needs — who actually won the bracket — is not read from Yahoo today.** This is a new data dependency, not just a code swap.
- Playoff *weeks* are modeled (`playoff_start_week=15`, `season_final_week=17`).
- Playoff *results* (bracket winner/runner-up/3rd) are NOT ingested. Must add a Yahoo postseason-result read (CORE-001 source of truth) feeding a new `_compute_playoff_placement_order()`.

## SPEC — rules to amend (grep-located)
| Rule | Current | Fix |
|---|---|---|
| §3 LED-344 | "60/30/10 by default" | state basis = postseason bracket |
| §4 Row-6 hybrid | "by final Yahoo **regular-season result**" | → **postseason bracket** finish |
| §4 BAB-405 | "official Yahoo **season result**" | → **postseason/playoff bracket** result |
| §4 BAB-407 | remainder in "final Yahoo **standing** order" | → **playoff placement** order |
| §7 CFG hybrid | "60/30/10 by final Yahoo **regular-season standing**" | → **postseason bracket** placement |

**Do NOT touch** skunk rules (§4 L291, AP-146, CFG-507, LED-345) — correctly regular-season Points For.

## Recommendation
Three-part fix, Opus-gated, batched with the Rev 2 economy/skunk review (shared season-close path):
1. **Data:** add Yahoo postseason bracket-placement reader → new `_compute_playoff_placement_order(league_id, db)`.
2. **Code:** switch the default in `_compute_standings_order` callers (`stripe_connect.py:554`, `settlement_report.py:80`, `api/main.py` payout route) to the playoff-placement order. Update docstrings at `stripe_connect.py:541` and `api/main.py:1359`. Keep the explicit-`standings_order` override.
3. **Spec:** amend the five rules above; leave skunk.
**Test gap to close:** add a case exercising the DEFAULT (no `standings_order` passed) so the regression is caught — the current suite passes the order explicitly and would stay green even with the wrong default.

## Existence-check provenance
Grep 2026-07-20, PowerShell, `FDCHub/fantasy-beefs` working tree. Distribution built: `stripe_connect.py` `preview_payouts`/`execute_payouts`/`_compute_standings_order`/`DEFAULT_PAYOUT_SPLIT`, `test_championship_payout.py` passing. Wrong basis: `stripe_connect.py:541`, `api/main.py:1359`. No bracket-result reader: all `playoff` hits are simulator/projection modules; `_compute_standings` is regular-season only.
