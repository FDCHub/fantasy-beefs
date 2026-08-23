# FINAL POR — IMPLEMENTATION ACCEPTANCE MATRIX

**Branch:** `postmvp/final-por-implementation`
**Base:** `766ea37b076d49bbbb2abb513cf6848941fcf184`
**HEAD:** see `git rev-parse HEAD` — updated per package.
**Status:** PARTIAL — 19 of 25 work packages complete. Every backend package is done; UI-2 is done. Not pushed, not deployed, not tagged.

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
| **WP-5** | §11/§13/§14 league-level minted pots; three season-scoped accounts; retire `reserve:{team}`, `championship:{league}`, bare `championship`, season-less `skunk:`, and the per-GM FS contribution model; Pool terminal remainders → FS Pot | **DONE** | **New:** `economy/championship_pots.py` (mint, `pot_balances`, `funded_pillars`, `no_gm_liability`, `terminal_pool_destination`); `migrations/add_ff_championship_pot.py` + manifest `0012`. **Changed:** `ledger/ledger.py` third door-bound exemption `CHAMPIONSHIP_POT_MINT_DOOR`/`championship_issuance:`; `economy/economy_events.py` pillar registry, `points_championship:`/`ff_championship:`/`championship_issuance:`, `pillar_season_key`, `RETIRED_FOR_FINAL_POR_*`; `economy/season_allocation.py` two-leg advance + `mint_season_pots` + era-aware replay comparison; `economy/skunk.py::skunk_pot_account`; `betting/pool_settlement.py` ×2, `betting/pool_funding.py` ×1 through the resolver; `betting/pool_legacy_guard.py` ruleset marker; `betting/shortfall_sweep.py` retired; `economy/season_reconciliation.py` reserve sweep + legacy consolidation retired; `economy/fantasystakes_championship_allocation.py::stage_allocation` refuses; `db/schema.py` + `economy/league_economy_config.py` + `payments/economy_config.py` FF pot amount | `test_finalpor_wp5_pot_architecture.py` — **104 PASS / 0 FAIL**, F1–F14. Base Pot identical at 4 and 10 GMs (14000 both); `no_gm_liability` reads back every mint leg and finds no GM account; a GM's obligations are 0 and Current Settle 0 after the whole league's pots are minted; FF pot of 0 records its event and posts no leg; Points pot refuses minting and holds exactly the Skunk assessed; a real terminal remainder lands in the FS pot; **no Final POR ledger entry touches any retired namespace**; replay mints 0; a LEGACY season keeps `skunk:{league}`, its reserve sweep and `championship:{league}` unchanged. **F14 runs `activate_season_allocation` end to end on SQLite** — buyin == min_reserve, reserve 0, no `reserve:` account created, snapshot matches posting, Base Pot minted, trial balance 0, replay idempotent |
| **WP-6** | §15 an approved Top-Off grows the FantasyStakes Championship Pot by the same amount; GM obligation stays X, not 2X | **DONE** | `economy/top_off.py::approve_top_off` step 15 — era-gated third leg: `bab_issuance:{L}:{S}` −2X, `wallet:{team}` +X, `fantasystakes_championship:{L}:{S}` +X. **Nothing else changed**: the obligation (`economy/current_settle.py::topoff_issued_cents`) and the cap (`economy/top_off.py::_issued_from_ledger`) both already summed the WALLET leg only, which is what made the leg safe to add and is exactly what WP-7 F6 certified in advance | `test_finalpor_wp6_topoff_pot_leg.py` — **49 PASS / 0 FAIL**, F1–F8. Legs are −2X/+X/+X and exactly three; obligation X and cap consumption X against the same 2X posting (two independent derivations, asserted separately); Current Settle moves by exactly 0; FS Score 0 and the door in neither scoring group; no receivable, no reserve, no other GM touched; issuance tally 2X and trial balance 0; a LEGACY season still posts exactly two legs with no pot leg and no pot created; two Top-Offs accumulate correctly on all four derivations |
| **WP-9** | §12 Points Championship: exists iff Skunk Fee > 0; pot = Skunk actually assessed; projection = fee × RS weeks (display only); 60/30/10; Points For ranking; provider tiebreak; true tie = dead heat; settles after regular-season provider corrections | **DONE** (provider tiebreak **BLOCKED** — see caveat) | **New:** `economy/points_championship.py` — `exists`/`pot_cents`/`projected_pot_cents`/`view`/`require_regular_season_final`/`distribute`, ranking on Points For scaled to integer hundredths, paying through `economy/championship_distribution.py`. `economy/skunk.py::distribute_season_skunk` delegates under the Final POR and keeps its legacy arithmetic byte-identical, sharing the SAME league-season event key so a season pays its Points pillar exactly once whichever era did it | `test_finalpor_wp9_points_championship.py` — **49 PASS / 0 FAIL**, F1–F9. `exists` and `funded` proven to be different questions on two real leagues; the fixture makes assessed (1500) and projected (2000) **differ** — a fully tied week assesses nothing — and the paid amount is the assessed figure; minting the pot to the projection is refused; 900/450/150/0 on a 1500 pot; ranking really descends by Points For; a genuine tie shares one place and one award to the cent with the whole pot still paid; an unfinalised regular-season week refuses settlement and pays nothing, then settles once the provider finalises it; replay pays nothing and exactly one event exists; a LEGACY season still pays 100% to the leader out of `skunk:{league}`. **Caveat:** §12's provider tiebreak has no source in this build — no provider standings ingest, no schema column carries a provider rank. `provider_tiebreak_available()` answers False honestly and nothing fabricates an ordering; an unbreakable tie is paid as §17's dead heat, which is the stated terminal outcome and invents no winner. The seam is in place for when a source is registered |
| **WP-12** | §10 Skunk corrections: REVERSE → RE-DERIVE → RE-POST; correction-aware event keys; provenance preserved | **DONE** | **New:** `economy/skunk_correction.py` — `correct_weekly_skunk`, `history`, `standing_assessment`. `economy/economy_events.py` gains `EVENT_SKUNK_ASSESSMENT_REVERSAL`/`_CORRECTION`, two distinct doors, and `correction_week_key(..., generation)`. `economy/skunk.py::SKUNK_SCORING_EVENT_TYPES` widened to the three-member family WP-3 had already designed it for | `test_finalpor_wp12_skunk_correction.py` — **64 PASS / 0 FAIL**, F1–F10. A no-change correction writes **no event and no ledger entry**; a real correction reverses the standing posting's own legs leg-for-leg, clears the wrongly-charged GM to 0 and charges the right one; **the reversal stays faithful after the governing fee is edited from 500 to 900** — it reverses 500 and re-posts 900; the standings read model reports the corrected Skunk **with no WP-12 code of its own**; the pot holds one fee after one correction and still one after two; keys are `gen0`/`gen1` and all distinct; the original event and its legs are still readable (3 events where 1 was, appended not replaced); a correction after the pot was distributed is refused by name having posted nothing; a legacy season and an unassessed week are both refused |
| **WP-13** | §7 accepted-wager void: accepted action still satisfies the Weekly Minimum; refund → Wallet; Minimum never restored; FS Score effect 0; escrow exact; auditable independent void event | **DONE** | **New:** `economy/wager_void.py` (`DOOR_WAGER_VOID`, `void_accepted_wager`, `is_voided`, `voided_bet_ids`); `db/schema.py::VoidedWager`; `migrations/add_voided_wagers.py` + manifest `0013`. `reports/standings_read_model.py` adds the door to `VERSUS_DOORS` — **that membership is the mechanism**, not bookkeeping. `betting/settlement_engine.py` excludes voided bets from its pending set. `economy/economy_events.py` gains `EVENT_WAGER_VOID` | `test_finalpor_wp13_wager_void.py` — **50 PASS / 0 FAIL**, F1–F10, over a REAL issued-and-accepted Locked challenge (`issue_funded_challenge` → `accept_funded_challenge`). Each GM's Wallet gets exactly their stake back and every escrow drains to 0; **not one cent reaches a `min:` account** and the refund legs are escrow-out/wallet-in only; the real WP-4 week close then sweeps 600 for the voided GMs and 1000 for the untouched ones, proving the accepted action still satisfied the Minimum and the stake was not forfeited twice; Score is 0 for all four GMs and `in_play` is 0; one `VoidedWager` row per bet plus one economy event; Bet rows are **not** relabelled `push`; a second void is refused and no Wallet moves; a never-accepted, already-settled, unexplained or legacy-era void is refused by name; the migration applies, is idempotent, and the DB itself refuses a duplicate bet_id and a negative refund |
| **WP-8** | §18 FS lifecycle LIVE→FINAL→PAID; postseason FS scoring stays LIVE; retire `championship_scoring_gate`, `REASON_POSTSEASON_CONTAMINATED` and the cutoff assumptions; dynamic FS Pot authoritative at finality | **DONE** | **New:** `economy/fantasystakes_lifecycle.py` — three states derived from posted state (the module writes nothing at all), `season_wide_cutoff` derived from `max(week)` across matchups/challenges/pool instances, `pot_cents` vs `authoritative_pot_cents` as two separate functions. `economy/championship_scoring_gate.py` returns unconditionally for a Final POR season, **before** the `playoff_start_week` requirement. `reports/championship_read_model.py::freeze_fantasystakes_championship` refuses with the new `REASON_FREEZE_RETIRED`, placed **after** the replay branch and **before** the contamination check | `test_finalpor_wp8_lifecycle.py` — **42 PASS / 0 FAIL**, F1–F9. A postseason action passes the gate with no freeze and no marker written; freezing is refused and the refusal is proven to precede the contamination check (comment lines stripped, so the prose naming both codes cannot confound the ordering) while the replay branch still precedes both; three states with **no FROZEN among them**; the cutoff is 7 on a 6-week fixture, not 18; the pot is 4000 while LIVE, grows to 8000, is refused as authoritative until FINAL, then readable; **a postseason wager really moves the Score — +300 / −300 where RC2 would have shown 0/0**; a LEGACY season still freezes at the boundary and the Final POR lifecycle refuses to describe it |
| **WP-11** | §14 Fantasy Football Championship structure; everything not blocked by provider evidence; no invented Yahoo bracket facts; settlement fail-closed and provider finality BLOCKED where unavailable | **DONE** for everything above the provider seam; **provider finality BLOCKED** | **New:** `economy/ff_championship_settlement.py` — `provider_finality` (three-valued), `podium`, `settle`. Pays the WP-5-minted `ff_championship:{L}:{S}` through `economy/championship_distribution.py`; resolves the podium through the certified `providers.identity` resolver | `test_finalpor_wp11_ff_championship.py` — **49 PASS / 0 FAIL**, F1–F10 against a hand-stated bracket. No state / UNKNOWN authority → BLOCKED, incomplete → NOT_COMPLETE (the two are distinguishable, which matters operationally); a tied final is an undecided game, not a dead heat; **the provider gate runs before the pot is read**, so an operator is never shown EMPTY_POT for a provider problem; a stated bracket pays 6000/3000/1000 of a 10000 pot and drains it; an unbound provider identity refuses and pays nobody; replay pays nothing; legacy era refused; **F10 walks the AST and proves no matchup classifier is called and no `championship_track` internal is imported**. **BLOCKED:** no end-to-end settlement against real Yahoo bracket data — no postseason payload is captured and no bracket-classifying field is documented. See §3. **FLAGGED OPEN PRODUCT QUESTION:** a bracket with no decided third-place game cannot settle. §17 requires the pot to be conserved exactly, so a two-name podium cannot go through the canonical splitter at all (demonstrated directly in F5); the POR states neither a redistribution rule nor a stranding rule, so this fails closed with a named reason rather than inventing one |
| **WP-14** | §20 Grand Championship = finalized championship VC across funded pillars; retire 3/2/1; ≥2 funded pillars; regular season placeholder with no rows; postseason live from finalized components; tied TOTAL = co-champions, no tiebreak | **DONE** | **New:** `economy/grand_championship.py` (`funded_pillars`, `finalized_pillars`, `view`, states PLACEHOLDER/LIVE/FINAL, `MINIMUM_FUNDED_PILLARS`). **Also new, and required first:** `economy/fantasystakes_championship_final.py` — WP-8 retired the boundary freeze, and RC2's settlement pays only a frozen snapshot, so the FS pillar could reach FINAL with **no way to be PAID**. It now pays the LIVE season-wide Score off the authoritative pot, writing the same `FantasyStakesChampionshipDistributionRun` row so PAID has one definition across both eras. `economy/championship_pots.py` gains `pillar_funded_cents` and `pillar_awards` | `test_finalpor_wp14_grand_championship.py` — **50 PASS / 0 FAIL**, F1–F10. The FS Championship pays 12000/4000/4000/0 of a 20000 pot with **no freeze marker anywhere** and refuses a second settlement; the fixture funds one pillar 20× the other and the Grand Champion is the GM who won the larger one — **the behavioural difference from 3/2/1**; **both pots are distributed to zero and both still count as FUNDED** (F4, the assertion a balance test would have failed); regular season returns `state=PLACEHOLDER` with `rows == []`, not rows of zeros; LIVE shows nothing for a funded-but-unpaid pillar — not a projection — then shows one pillar, then FINAL; **a constructed dead heat at 700/700 names both GMs as co-champions**, reached by opposite routes (600/100 vs 100/600); F9 proves the module posts nothing and reading it twice moves no Wallet; F10 walks the AST to prove `reports.grand_champion` is not imported |
| **WP-15** | §21/§22 My Settle reshape — six concepts separate; reconstructed from ledger provenance; remove `expired_min` asset treatment and the per-GM championship obligation; Skunk via event provenance; Top-Off pot leg must not double the obligation; awards enter Wallet once; optional external mapping with SUM(owed)=SUM(receivable) | **DONE** | `economy/current_settle.py` — `is_final_por` and `skunk_cents` on the row, `expired_min` excluded from Final POR assets, Skunk read through `cumulative_skunk_fees_cents` under the Final POR and the raw `receivable:` under the legacy era (**one source per era, never both**). **New:** `economy/external_mapping.py` — `frozen_participant_field` (from `SeasonAllocation`, not today's roster), `minted_championship_cents` (the issuance tally, so only MINTED Credits attract dues), `split_equally`, `reconcile` | `test_finalpor_wp15_settle_reshape.py` — **59 PASS / 0 FAIL**, F1–F10. FS Score is absent from the row and the module reads no pot account or issuance tally; **750 cents are forced into `expired_min:` and Current Settle does not move** — the omission is deliberate, not an accident of empty data; the Final POR opening allocation settles to **exactly 0** where the retired model was −8000 by design; a WP-12 correction moves the Skunk obligation from one GM to another and both settle figures follow; **2X into circulation for X of Wallet moves Current Settle by 0**; a 4000 award raises Current Settle by 4000 and creates no obligation; the mapping writes no ledger entry; dues are equal shares summing to the minted total with the remainder by ascending id; **SUM(owed) == SUM(receivable)**, and after an award is paid the winner's `owed` falls by exactly the award while dues are unchanged — paying a pot does not un-mint it |
| **WP-18** | Update the governing active specs so they no longer contradict implemented Final POR behaviour; preserve old specs only as explicitly superseded historical evidence | **DONE** | **New:** `spec/FANTASYSTAKES_FINAL_POR.md` — the governing active spec, stating all eleven required behaviours with the implementation module and certification suite named beside each, plus §13 "what is NOT settled" (Yahoo UNKNOWN, bracket BLOCKED, third-place OPEN, PostgreSQL NOT RUN). Supersession headers added to `spec/RC2_CHAMPIONSHIP_POR.md` (full) and `spec/FantasyBeefs_Merged_Section_4_BABEconomy.md` (partial, **by BAB rule identifier**). Neither is edited below its header | `test_finalpor_wp18_spec_supersession.py` — **55 PASS / 0 FAIL**, F1–F10. All eleven behaviours stated; **all 18 named modules and all 14 cited suites exist**; both superseded docs are marked at the very top, name their successor, say they still govern legacy seasons, and are proven **unedited below the header** (RC2's 3/2/1 table, boundary rule and per-GM contribution rule all still present verbatim); the spec's era constants, four pot account names, 60/30/10 split, dead-heat examples, remainder convention and pillar minimum are each checked **against the code that defines them**, so a rename fails a test rather than ageing the document silently |
| **WP-16** | Complete the governed retirements once their replacements are live | **DONE** | No new production code — the retirements landed with the packages that replaced them (WP-4/5/8/12/13/14/15), each era-gated and each individually certified. WP-16 is the **sweep** that proves nothing is left half-retired | `test_finalpor_wp16_retirements.py` — **55 PASS / 0 FAIL**, F1–F6. The register is **data**, cross-checked against `RETIRED_FOR_FINAL_POR_*` in the code so a forgotten retirement is a visible omission. **F2 plays a whole Final POR season end to end** — activation, mint, two week releases, a partial spend, two Skunk assessments, a WP-12 correction, two week closes, a three-leg Top-Off, a terminal Pool remainder and the FantasyStakes Championship payout — then reads all 25 touched accounts back and proves **not one** is `expired_min:`, `reserve:`, `championship:`, bare `championship` or `skunk:`. All seven retired callables refuse or report `retired=True` and **move nothing**. The legacy era still runs every one of them (a legacy season writes `expired_min:` 1000, `skunk:` 500, `reserve:` 8000, sweeps 32000 into `championship:{league}` and returns the Minimum to Wallet). **F5 proves no retirement was completed by deletion** — every callable still exists, still consults the era gate, and `REASON_POSTSEASON_CONTAMINATED` and the 3/2/1 table survive for legacy readers. The season conserves, every door used is a named governed one, and the three retired doors are absent |
| **UI-2** | §26 six-column Standings — `RK \| TEAM \| MATCHUPS \| POOLS \| SKUNK \| FS SCORE` at 320×568 / 375×667 / 390×844; no horizontal page scroll; no header ellipsis; all six columns remain; TEAM usable; header/body one grid; no bottom-nav collision; approved explanatory copy | **DONE** | `web/js/standings-model.js` — six columns, a `skunk` cell kind; `web/js/standings.js` — `skunkCell` (unsigned, untoned, `—` at zero) and `STANDINGS_EXPLAINER_LINES`; `web/styles/standings.css` — a re-budgeted six-column track contract scoped to the OVERALL table only, header wrapping with **no ellipsis**, and the figure-header left-inset reclaim; `web/styles/tokens.css` — `--fs-st-head-6col: 12px` | `test_finalpor_ui2_standings.py` → `web/tests/finalpor_ui2_standings.mjs` — **54 PASS / 0 FAIL in real headless Chrome at all three widths**. Measured, not inferred: doc scrollWidth == clientWidth at 320/375/390; six `<th>` and six `<td>` at every width; **no header clipped** (`scrollWidth <= clientWidth` on every `th`); header row 23px, one line; TEAM 46/101/116px and truncating inside its container; header and body share one grid to the pixel; table bottom clears the nav; the approved three sentences present verbatim; SKUNK is the fifth column, unsigned, untoned |
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

**Every backend package — WP-4, WP-5, WP-6, WP-8, WP-9, WP-11, WP-12, WP-13, WP-14, WP-15, WP-16 and WP-18 — is complete and are no longer listed here.** **Every backend work package is complete, and UI-2 is complete.** The next packages are **UI-3A–D** (Play), **UI-5** (Wrap Up), **UI-7** (Rules / League Settings), and finally **WP-17** (demo).

| WP | Requirement | Why it matters |
|---|---|---|
| **WP-17** | demo re-fixture | Waits on the UI packages; the demo must visibly demonstrate the new economy. |
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

### Replaced during WP-4/WP-5 (this continuation) — four more

| File | Encoded | Replaced with |
|---|---|---|
| `test_championship_payout.py` Item 8 | "**exactly one** production call site posts a `reserve:{...}` leg" — the RETIRED architecture stated as correct, matched only when the leg tuple was written INLINE in the `post()` call. WP-5 made the leg conditional, so the matcher stopped seeing the very site it existed to police and would have passed while blind. | The claim is kept and strengthened: a leg-shaped reserve tuple is found **however the legs are assembled**; every site must belong to an enumerated governed set by file AND function; and each of those functions must be **era-gated**, so no Final POR season can reach one. A second-element-is-a-string filter excludes pure data declarations without excluding anything that could post. |
| `test_b1_schema_readiness.py` §5 | "every active migration is verifiable by table or column" — which a data backfill and a widened CHECK legitimately cannot satisfy, so it could not tell a legitimate object-free migration from an author who forgot to fill the fields in. | "verifiable, **or says why it cannot be**", backed by a new required `Migration.adds_no_object` rationale, plus a second assertion that the reason is substantive. A migration that adds objects and forgets to name them still fails — the protection B1 exists to give. |
| `test_uirecon_wave5.py`, `test_uirecon_rev14_presentation.py` | Scope guards that unioned `git diff --name-only HEAD` — the **working tree** — into "the files this package changed". Once the package was committed this could not attribute authorship, so it flagged **any** later uncommitted edit to a frozen file as a violation by that package. Both fired on WP-5's governed `betting/pool_settlement.py` change. | Re-anchored to each package's **own commits**, found by commit subject, which measures exactly what the assertion says and keeps doing so. If those commits are not reachable the working tree is used as before, so the guard still bites while the package is genuinely in progress. `test_uirecon_wave5.py` additionally asserts the guard really examined a non-empty file set, so it cannot pass by looking at nothing. |
| `web/tests/uirecon_wave4_browser.mjs` | `titles[0] === 'ON OFFER'` or `'RESULT'` — the pre-UI-3E order. **The previous run replaced this in `e2e_package2.mjs`, `e2e_package3.mjs` and `package2_component_tests.mjs` and missed this file**; it did not surface then because WP-5 is what made the surrounding suite run to that point. | §27E's order asserted directly — LINEUPS leads, the market block is still present, and it sits below LINEUPS — which keeps the original claim (the sheet must not lead with a second copy of the two team names) whole. `test_uirecon_wave4.py` → 186 PASS / 0 FAIL. |

`test_uirecon_wave4.py` also gained an entry in its **existing** `_AUTHORISED_LATER`
table — the mechanism that file already provides so an exception must be *written
down* rather than discovered as a silent pass — recording exactly what WP-5 was
authorised to change in `betting/pool_settlement.py` and which suite pins it.

---

## 5. TEST EXECUTION RESULTS

Final sweep, this branch:

| Suite | Result |
|---|---|
| `test_finalpor_wp4_minimum_sweep.py` | **59 PASS / 0 FAIL** |
| `test_finalpor_wp5_pot_architecture.py` | **104 PASS / 0 FAIL** |
| `test_finalpor_wp6_topoff_pot_leg.py` | **49 PASS / 0 FAIL** |
| `test_finalpor_wp9_points_championship.py` | **49 PASS / 0 FAIL** |
| `test_finalpor_wp12_skunk_correction.py` | **64 PASS / 0 FAIL** |
| `test_finalpor_wp13_wager_void.py` | **50 PASS / 0 FAIL** |
| `test_finalpor_wp8_lifecycle.py` | **42 PASS / 0 FAIL** |
| `test_finalpor_wp11_ff_championship.py` | **49 PASS / 0 FAIL** |
| `test_finalpor_wp14_grand_championship.py` | **50 PASS / 0 FAIL** |
| `test_finalpor_wp15_settle_reshape.py` | **59 PASS / 0 FAIL** |
| `test_finalpor_wp16_retirements.py` | **55 PASS / 0 FAIL** |
| `test_finalpor_wp18_spec_supersession.py` | **55 PASS / 0 FAIL** |
| `test_finalpor_ui2_standings.py` | **54 PASS / 0 FAIL** (headless Chrome, 3 viewports) |
| `test_uirecon_wave2.py` | **1016 PASS / 0 FAIL** (was 993/21 at `fc57288`) |
| `test_wp3c_rev43_gameplay.py` | **270 PASS / 0 FAIL** |
| `test_wp3b_rev43_foundation.py` | **282 PASS / 0 FAIL** |
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

### Previously-known failures — BOTH NOW RESOLVED BY WP-5

| Suite | Was | Now |
|---|---|---|
| `test_championship_payout.py` | "exactly one production call site posts a `reserve:{...}` leg" — 3 sites. Predicted to resolve at WP-5. | **17 PASS / 0 FAIL.** Resolved as predicted, and the guard was REPLACED rather than relaxed — see §4. |
| `test_b1_schema_readiness.py` | `0009_pool_definition_public_question_backfill` declared no verifiable object (pre-existing at base). WP-2 silently added a second offender, `0011_skunk_fee_allows_zero`, which the previous matrix did not record. | **33 PASS / 0 FAIL.** `Migration.adds_no_object` now carries a required written reason; the check demands an object OR a stated reason. A migration that adds objects and forgets to name them still fails. |

### Known failures NOT caused by this branch (verified at base `766ea37`)

| Suite | Failure | Verification |
|---|---|---|
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
- **Browser suites are timing-sensitive** when run in rapid succession — reconfirmed this run: `test_s7_p4_rules_commissioner.py` failed inside a back-to-back sweep and passed cleanly (367 PASS / 0 FAIL) when run alone. Treat isolated browser failures as suspect until re-run.
- **`test_wp3d_provider_attribution.py` is NOT a usable signal in this environment, and is NOT attributable to WP-4/WP-5.** Measured on four trees: base `766ea37` → 2 failing browser modes / 387 PASS; `6b576c1` (WP-1, a pure backend change touching no `web/js`) → 5 modes / 169 PASS; `604f2b9` (UI-1) → 4 modes / 241 PASS; `fc57288` (previous HEAD, before any of this continuation's work) → 5 modes / 289 PASS. The PASS count swings from 169 to 387 across identical trees, so the suite is non-deterministic here — most likely headless-Chrome resource contention. **WP-4 and WP-5 changed no file under `web/js` at all** (verified by `git diff --name-only fc57288 -- web/js/*` → empty), so no runtime UI behaviour moved. The degradation between base and `fc57288` predates this continuation and is flagged for the UI packages to investigate on a quiet machine.
- **`test_s4_pool_engine_unit.py` fails on console encoding, not on code.** Windows `cp1252` stdout cannot encode a box-drawing character the suite prints. `PYTHONIOENCODING=utf-8 python test_s4_pool_engine_unit.py` → **53 PASS / 0 FAIL, exit 0**. `betting/pool_engine.py` was not modified by this continuation.

---

## 6. DEFECTS FOUND DURING IMPLEMENTATION

### Found and fixed during WP-5

4. **A Final POR season could not be re-activated idempotently.** `activate_season_allocation`'s replay path compares each stored `SeasonAllocation` row against `(stop.buyin_cents, stop.min_reserve_cents, stop.reserve_cents)`. WP-5 makes a Final POR season store `(min_reserve, min_reserve, 0)`, so **every** replay raised `ConflictingAllocationError` — the season's own correct rows read as a conflict with itself. Fixed by computing the expected tuple the way the posting does, from the season's stamped era; a legacy season keeps the original comparison byte for byte. **Found only because WP-5's certification runs a real activation end to end on SQLite (F14)** — the PostgreSQL-only allocation suites that normally cover this function cannot run in this environment, and the source-level assertion in F7 would never have caught it.

5. **`stage_allocation`'s two `reserve:` postings were unreachable-but-ungated.** They were the second and third of the three sites `test_championship_payout` had been failing on. Now refused at function entry for a Final POR season, before any posting, with the era gate asserted to *precede* the posting in source order.



1. **`posting_id` does not join across `economy_event` and `ledger_entries` on SQLite.** Both are declared `Uuid`; `record_event` inserts `str(uuid)` through raw SQL (dashed, 36 chars) while `ledger.post` inserts through the ORM (dashless, 32 chars). A plain equality join returns **zero rows on SQLite and every row on PostgreSQL**. Nothing had ever joined these two tables, so it had never surfaced. Worked around by normalising both sides at read time; the write format is deliberately unchanged, because normalising it would orphan every `economy_event` row already written on a SQLite deployment. **This remains a latent trap for any future cross-table posting join.**

2. **A second, divergent rail-heading builder** existed in `web/js/data/action-data.js` with different words for the same four rails. Aligned.

3. **Three championship split implementations, two of which disagreed about ties** — confirming the second review's finding. `economy/championship.py` paid a dead heat 60/30 by list-construction order and pays the Fantasy Football pot. Consolidated.

---

## 7. EXPLICITLY NOT DONE

- No push, no deploy, no tag, no branch beyond the local implementation branch.
- No production database touched. No Yahoo configuration or secret read, written or exposed.
- The separate public marketing website was not touched (§40).
- **WP-18 is now DONE and this debt is cleared.** `spec/FANTASYSTAKES_FINAL_POR.md` is the governing active spec; `spec/RC2_CHAMPIONSHIP_POR.md` and `spec/FantasyBeefs_Merged_Section_4_BABEconomy.md` carry explicit supersession headers and are otherwise unedited. `test_finalpor_wp18_spec_supersession.py` checks the spec against the code that defines each constant, so the drift cannot recur silently.
