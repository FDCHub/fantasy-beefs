# FINAL POR — IMPLEMENTATION ACCEPTANCE MATRIX

**Branch:** `postmvp/final-por-implementation`
**Base:** `766ea37b076d49bbbb2abb513cf6848941fcf184`
**HEAD:** see `git rev-parse HEAD` — updated per package.
**Status:** PARTIAL — 7 of 25 work packages complete. Not pushed, not deployed, not tagged.

Classification is `DONE` only where there is **executed test evidence**, not a
change summary. Anything implemented but not certified is marked explicitly.

---

## 1. COMPLETED WORK PACKAGES

| WP | Requirement | Status | Implementation evidence | Test evidence |
|---|---|---|---|---|
| **WP-1** | §4 season-level `ruleset_version`; historical seasons keep original rules; absence explicitly governed; PG/SQLite parity | **DONE** | `ruleset.py`; `db/schema.py::LeagueSeasonRuleset`; `migrations/add_season_ruleset.py`; stamped inside `economy/season_allocation.py` activation txn; manifest `0010_season_ruleset` | `test_finalpor_wp1_ruleset.py` — 22 PASS / 0 FAIL. Absence→LEGACY, replay no-op, contradiction refuses, unknown version refuses on read *and* write, DB uniqueness, Base-metadata registration |
| **UI-1** | §31 shared shell/carousel; `mountApplication` → `goTo(DEFAULT)` defect; all 3 families at 3 widths | **DONE** | `web/js/shell.js` — `ACTIVE_DESTINATION_ID`, `captureRailScroll`/`restoreRailScroll`, `goTo(..., {keepSheet})`, `mountApplication({preserveContext})`; all 3 mutation call sites updated | `test_finalpor_ui1_shell_context.py` — 13 PASS / 0 FAIL **in real headless Chrome**. Reader stays on Play; carousel holds 371→371; no horizontal page scroll on any tab at 320×568 / 375×667 / 390×844; all 3 families present (Play 2 `.fs-carousel`, Status 4 `.fs-rail--carousel`, Wrap Up 3 `.fs-rescar`) |
| **WP-10** | §17 one canonical 60/30/10 + dead heat for all pillars; retire rivals | **DONE** | `economy/championship_distribution.py` (new canonical); `reports/championship_read_model.py::tied_championship_distribution` delegates; `economy/season_reconciliation.py` switched off `economy/championship.py`'s tie-less arithmetic | `test_finalpor_wp10_distribution.py` — 43 PASS / 0 FAIL. §17's three worked examples verbatim (45%/20%/5%), ten pots 0→999,999 conserve, ascending-id remainder, bracket reports no tie |
| **WP-4** | §5 unused Weekly Minimum → FantasyStakes Championship Pot at WEEK close; no Wallet return, no `expired_min:`, no receivable, no Score effect; retire the Frozen Return | **DONE** | `economy/economy_events.py` — `fantasystakes_championship_account`, `EVENT_WEEKLY_MINIMUM_SWEEP`, `DOOR_WEEKLY_MINIMUM_SWEEP`; `economy/weekly_minimum.py::expire_weekly_minimum` era-gated, `ExpiryResult.destination`; `economy/season_reconciliation.py::reconcile_expired_minimum` returns `retired=True` under Final POR and posts nothing; `economy/season_close_orchestrator.py` reports `expired_min_step_retired`; `api/main.py::WeekCloseOut.minimum_destination`; `economy/fantasystakes_championship_allocation.py::pot_account` now delegates | `test_finalpor_wp4_minimum_sweep.py` — **59 PASS / 0 FAIL**. All ten required proofs: full-consumption sweeps 0, 400-spent sweeps exactly 600, 999-spent sweeps exactly 1, zero-spend sweeps the whole Minimum, door legs sum to 0 and trial balance 0, no `wallet:` leg and every Wallet still 0, no `expired_min:`/`receivable:`/Skunk, Score moves 0 and the door is in neither scoring group by name, Current Settle falls by exactly 600 entirely out of `weekly_min_live` with obligations unchanged, replay grows the pot by 0, and a LEGACY season keeps the old account, event type, door, zero-settle-delta and season-close Wallet return |
| **WP-2 (part)** | §8/§9D Weekly Skunk Fee may be 0 at validator, DB CHECK and API | **DONE** | `economy/league_economy_config.py` `MIN_SKUNK_FEE_CENTS=0`; `db/schema.py` CHECK `BETWEEN 0`; `api/main.py` `Field(ge=0)`; `migrations/relax_skunk_fee_allows_zero.py`; manifest `0011` | `test_finalpor_wp2_skunk_zero.py` — 25 PASS / 0 FAIL. Plus a live SQLite rebuild proof: legacy frozen 2025 row survives byte-for-byte, replay is a no-op, negative still refused, other 4 CHECKs survive |
| **WP-3** | §9 Skunk season-scoped per-team derivation | **DONE** | `economy/skunk.py::skunk_fees_by_team` / `cumulative_skunk_fees_cents`; `SKUNK_SCORING_EVENT_TYPES` enumerated by name | Same suite. Tied week attributes 2.5+2.5 not 5+5; season 2027 does not inherit 2026; `shortfall_sweep` receivable excluded; non-Skunk event excluded |
| **WP-7** | §8 FS Score = Matchups + Pools − Skunk; era-gated; positive magnitude | **DONE** | `reports/standings_read_model.py` — `skunk_fees_cents` field, 3-term `net_cents`, `is_final_por` gate, `as_dict`; `api/main.py::StandingsRowOut` | `test_finalpor_wp7_fs_score.py` — 16 PASS / 0 FAIL. Same fixture under each ruleset gives 0 vs −500; Skunk changes *ranking*; Top-Off principal moves Score by exactly 0 while crediting Wallet |
| **UI-4** | §28 four locked Status category names + `LABEL · N · SWIPE` | **DONE** | `web/js/action.js::RAIL_WORDS` + `railHeading`; `web/js/data/action-data.js::railHeading` (second builder aligned) | `test_uirecon_rev14_status.py` 38 PASS, `test_uirecon_wave5.py` 37 PASS, `test_s8_p4c2_action.py` all PASS, `package2_component_tests.mjs` all PASS |
| **UI-6** | §30 all four Account cards closed; HELD→ESCROW; Opening FantasyStakes Allocation | **DONE** | `web/js/ledger.js` — `open: false`, `{label:'Escrow', context:'included in In Play'}`, `OPENING FANTASYSTAKES ALLOCATION` | `test_s7_p3_week_ledger.py` 452 PASS / 0 FAIL; `test_uirecon_rev14_presentation.py` 319 PASS / 0 FAIL (incl. 3 viewports) |
| **UI-3E** | §27E LINEUPS above ON OFFER | **DONE** | `web/js/preview.js::previewSheet` body order | `test_s7_p2_league_action.py` 484 PASS / 0 FAIL; `e2e_package2.mjs`, `e2e_package3.mjs` order assertions replaced and green |

### Verified-as-already-correct (no change required)

| Requirement | Evidence |
|---|---|
| §5 spend order Minimum→Wallet | `economy/spend_sourcing.py::plan_spend_split` is the sole implementation, used by both Matchups and Pools. POR explicitly says do not rewrite. |
| §25 Wallet 0 at activation, Week 1 not pre-funded | `economy/season_allocation.py` posts `min_reserve` + `reserve` only; no wallet leg. |
| §9F postseason Wallet-only | Emergent: `min:{T}:{postseason_week}` is never released, so `plan_spend_split` returns a Wallet-only leg with no branch. |
| §5 rejected/expired/never-accepted do not count | `economy/challenge_funding.py::_reverse` replays source-faithfully to `min:`; settlement credits Wallet only. |
| §16 3 TEAM + 1 MATCHUP slate | `betting/pool_rotation.py::DEFAULT_SCOPE_MIX = ((TEAM,3),(MATCHUP,1))`; catalog `weekly_slate_composition` matches; loader refuses a disagreeing catalog. |
| §19 third-place fail-closed | `season/championship_track.py::_identify_third_place` — semifinal-loser participant set, affirmative NON_CHAMPIONSHIP, refuses ambiguity, no fallback. |
| §32 no public "Versus" | Appears only in comments, docstrings, internal identifiers and JSON field names; no rendered string. Rendered label is already `Net Matchups`. |
| §23 Bet Privacy / Quiet Ledger removal | No such field exists anywhere in schema, API or JS. No-op. |

---

## 2. NOT STARTED — remaining work packages

Each is **NOT IMPLEMENTED**. None was partially applied; there is no half-converted
account model and no half-applied migration on this branch.

**WP-4 is complete and is no longer listed here.** The next package is **WP-5**.

| WP | Requirement | Why it matters |
|---|---|---|
| **WP-5** | §11/§13/§14 league-level minted pots; `ff_championship:{L}:{S}`; season-scope `skunk:`; retire `reserve:{team}` and `championship:{league}` new writes; Pool terminal remainders → FS Pot | The pot architecture is unchanged. `championship:{league}` still accretes from 5 paths. |
| **WP-6** | §15 Top-Off third leg → FS Pot | Top-Off still posts 2 legs. Certified that the Wallet-leg-only cap and obligation derivations remain correct (WP-7 F6), so the leg can be added safely. |
| **WP-9** | §12 Points Championship pot = actual Skunk assessed, 60/30/10, settles at regular-season end | Still `distribute_season_skunk` → 100% to Points For leader. |
| **WP-12** | §10 Skunk reverse/re-derive/re-post corrections | `SKUNK_SCORING_EVENT_TYPES` is the seam and is documented for it; correction event types not yet added. |
| **WP-13** | §7 accepted-wager void | No void path exists. |
| **WP-8** | §18 FS lifecycle LIVE→FINAL→PAID; retire `championship_scoring_gate`, `REASON_POSTSEASON_CONTAMINATED`, cutoff CHECK, fixed-pot assumptions | Freeze still happens at the playoff boundary. |
| **WP-11** | §14 FF Championship pot, provider-gated | — |
| **WP-14** | §20 Grand Championship as finalized pillar VC; retire 3/2/1 | `reports/grand_champion.py` unchanged. |
| **WP-15** | §21/§22 My Settle reshape + optional external mapping | — |
| **WP-16/17/18** | retirements, demo re-fixture, spec supersession | Specs still describe the old model. |
| **UI-2** | §26 six-column standings incl. the 320px responsive grid | Backend contract (`skunk_fees_cents`) is DONE and shipped; the UI column is not drawn. |
| **UI-3 (A–D)** | §27 carousel position beyond the shell fix, odds-refresh icon, one-row market microcopy, 3+1 visible, demo rollover | UI-1 fixed the shell-level cause; card-level work not done. |
| **UI-5** | §29 Wrap Up expansion, X close, analysis panels | Three carousels already exist and are correctly headed. |
| **UI-7** | §24 Rules card, §23 seven-row League Settings | Prop Pool Entry not yet moved into the economy table. |
| **PROV-0/1/2** | §33 Yahoo | See below. |
| **AUDIT-1** | §38 independent acceptance audit | This document is the artifact; the audit itself is external. |

---

## 3. YAHOO PROVIDER — CURRENT STATE

**Current authorization state: UNKNOWN. No fresh probe was possible.**

- No `YAHOO_PRIVATE_JSON` / `YAHOO_CONSUMER_SECRET` in the environment.
- No `secrets/` directory (the documented fallback path).
- `provider_grants` table: 0 rows. Local DB holds only synthetic `pds1.*` test leagues.
- `yfpy` **is** installed, so client capability exists; credentials do not.
- I also declined on principle: exercising credentials requires an OAuth refresh, which rotates token state, and §1 forbids mutating provider configuration.

The 403 finding in `providers/certify/run.py` is dated **2026-08-15** and is
**stale repository evidence, not current verified state**.

**PROV-1 and PROV-2 remain required regardless of authorization**, because no
postseason payload is captured, no bracket-classifying field is documented, and
no Yahoo postseason source is registered. Nothing in this branch fakes playoff,
consolation, championship or third-place classification; UNKNOWN still fails closed.

---

## 4. TESTS REPLACED BECAUSE THEY ENCODED THE OLD POR

Eleven suites. Each replacement **preserves the claim the assertion was
originally making** and states why in a comment at the site.

| File | Encoded | Replaced with |
|---|---|---|
| `test_wp3b_rev43_foundation.py` | literal source string of the 2-term FS Score identity | the 3-term identity + the era gate + "still no balance is read" |
| `test_wp3b_standings_read_model.py` | exact competitive field set | field set incl. `skunk_fees_cents`, plus a legacy-ruleset two-term assertion |
| `test_uirecon_rev14_presentation.py` | **"it was NOT renamed Escrow"** — a Rev 1.4 refusal | requires the rename AND the `included in In Play` safeguard that answers the original objection |
| `test_uirecon_rev14_status.py` | old rail names + `LABEL: N` | locked names + `LABEL · N · SWIPE` + the SWIPE import |
| `test_uirecon_wave5.py` | old rail names | locked names |
| `test_s8_p4c2_action.py` | `${word}: ${sectionCount(rail)}` | the new one-expression grammar (claim unchanged: one builder, no per-rail wording) |
| `test_s7_p3_week_ledger.py` | `Held` strip label | `Escrow`; the cents assertion is untouched |
| `test_uirecon_rc4_parallel.py` | manifest regex anchored to the end of ACTIVE | anchored to 0009's own entry — what it always meant |
| `web/tests/package2_component_tests.mjs` | both rail-heading builders + preview order | locked names/grammar + LINEUPS-first |
| `web/tests/e2e_package2.mjs` / `e2e_package3.mjs` | rail wording, preview order, `FANTASYSTAKES ADVANCES`, `Held` | Final POR equivalents |
| `wp3c_*`, `p4b2_gm`, `p4c5_integration`, `package3_component`, `uirecon_rev14_presentation_browser` | `Held` label | `Escrow` |

---

## 5. TEST EXECUTION RESULTS

Final sweep, this branch:

| Suite | Result |
|---|---|
| `test_finalpor_wp4_minimum_sweep.py` | **59 PASS / 0 FAIL** |
| `test_finalpor_wp1_ruleset.py` | 22 PASS / 0 FAIL |
| `test_finalpor_wp2_skunk_zero.py` | 25 PASS / 0 FAIL |
| `test_finalpor_wp7_fs_score.py` | 16 PASS / 0 FAIL |
| `test_finalpor_wp10_distribution.py` | 43 PASS / 0 FAIL |
| `test_finalpor_ui1_shell_context.py` | 13 PASS / 0 FAIL (headless Chrome, 3 viewports) |
| `test_wp3b_rev43_foundation.py` | 279 PASS / 0 FAIL |
| `test_wp3b_standings_read_model.py` | 65 PASS / 0 FAIL |
| `test_s7_p2_league_action.py` | 484 PASS / 0 FAIL |
| `test_s7_p3_week_ledger.py` | 452 PASS / 0 FAIL |
| `test_uirecon_rev14_presentation.py` | 319 PASS / 0 FAIL |
| `test_uirecon_wave3.py` | 812 PASS / 0 FAIL |
| `test_uirecon_wave5.py` / `rev14_status` | 37 / 38 PASS, 0 FAIL |
| `test_s8_p4c2_action.py` | all PASS |
| `test_s8_p3_read_models.py` | 73 PASS / 0 FAIL |
| `test_rc2_championship*` (4 suites) | 112 PASS / 0 FAIL |
| `test_championship_distribution.py` | 300 PASS / 0 FAIL |
| `test_ledger.py` / `test_economy_config.py` | 48 / 31 PASS, 0 FAIL |
| `test_shortfall_sweep.py` / `test_shortfall_reporting.py` | 46 / 23 PASS, 0 FAIL (re-run for WP-4) |
| `test_s7_p4_rules_commissioner.py` | 367 PASS / 0 FAIL (re-run for WP-4) |
| `test_wp3b_rev43_foundation.py` / `test_wp3b_standings_read_model.py` | 282 / 66 PASS, 0 FAIL (re-run for WP-4) |

### Known failures NOT caused by this branch (verified at base `766ea37`)

| Suite | Failure | Verification |
|---|---|---|
| `test_b1_schema_readiness.py` | `0009_pool_definition_public_question_backfill` declares no verifiable object | Reproduced at base by stash |
| `test_championship_payout.py` | "exactly one production call site posts a `reserve:{...}` leg" — 3 sites | Reproduced at base. **Resolves when WP-5 retires `stage_allocation`'s reserve legs.** |
| `test_s7_p1_ui_shell.py` → `e2e_shell.mjs` | `Cannot read properties of null` | Reproduced at base. One of the "known carousel/UI regressions" at 766ea37. |

### Certification NOT performed

- **PostgreSQL parity: NOT RUN.** No `TEST_DATABASE_URL` in this environment. Every
  `*_pg.py` suite is unexecuted, and each refuses cleanly rather than falling back to
  `DATABASE_URL`. The SQLite half of the constraint migration is proven; the
  PostgreSQL half is written but unexecuted.
- **A PostgreSQL server IS listening on `127.0.0.1:5433`** (verified by protocol
  handshake — it answers an SSLRequest with `N`; port 5432 is closed and `psql` is
  not on PATH). No credentials for it exist in this environment and I did not attempt
  authentication against an unidentified server. **If a disposable `*_test` database on
  5433 is made available via `TEST_DATABASE_URL`, PostgreSQL parity becomes runnable
  immediately** — this is the single highest-value unblock available on this branch.
  Until then every PG claim stays NOT RUN.
- **Browser suites are timing-sensitive** when run in rapid succession — one WP3B run in a back-to-back sweep failed and passed cleanly twice when run alone. Treat isolated browser failures as suspect until re-run.

---

## 6. DEFECTS FOUND DURING IMPLEMENTATION

1. **`posting_id` does not join across `economy_event` and `ledger_entries` on SQLite.** Both are declared `Uuid`; `record_event` inserts `str(uuid)` through raw SQL (dashed, 36 chars) while `ledger.post` inserts through the ORM (dashless, 32 chars). A plain equality join returns **zero rows on SQLite and every row on PostgreSQL**. Nothing had ever joined these two tables, so it had never surfaced. Worked around by normalising both sides at read time; the write format is deliberately unchanged, because normalising it would orphan every `economy_event` row already written on a SQLite deployment. **This remains a latent trap for any future cross-table posting join.**

2. **A second, divergent rail-heading builder** existed in `web/js/data/action-data.js` with different words for the same four rails. Aligned.

3. **Three championship split implementations, two of which disagreed about ties** — confirming the second review's finding. `economy/championship.py` paid a dead heat 60/30 by list-construction order and pays the Fantasy Football pot. Consolidated.

---

## 7. EXPLICITLY NOT DONE

- No push, no deploy, no tag, no branch beyond the local implementation branch.
- No production database touched. No Yahoo configuration or secret read, written or exposed.
- The separate public marketing website was not touched (§40).
- Specs were **not** superseded (WP-18 not started) — governing specs still describe the old model and now disagree with the code in the areas WP-1/2/3/7/10 changed. This is the most important documentation debt on the branch.
