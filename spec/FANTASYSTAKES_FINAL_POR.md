# FantasyStakes — FINAL POR

Status: **GOVERNING ACTIVE SPEC**
Supersedes: `spec/RC2_CHAMPIONSHIP_POR.md` (for `RULESET_FINAL_POR` seasons only)
Era gate: `ruleset.py` — `RULESET_LEGACY = 1`, `RULESET_FINAL_POR = 2`

---

## 0. What this document is, and what it is not

This is the **implemented** Final POR: every rule below is in the code and is
covered by an executed certification suite named beside it. It is not a plan and
not a proposal. Where a rule was implemented differently from how a reader might
expect, the reason is stated here rather than only in the source.

**It governs Final POR seasons only.** Every season activated before WP-1 carries
no ruleset row, which *is* `RULESET_LEGACY`, and continues to be governed by the
documents this one supersedes. Nothing here is retroactive: no historical score
was recomputed, no paid award revisited, no posting rewritten.

**Absence of a row is a governed state, not missing data.** That is the single
convention the whole era gate rests on.

---

## 1. The era gate — `ruleset_version` (WP-1)

One integer per league-season, stamped inside the activation transaction and
never updated in place. One version, not three, because the Final POR changes
scoring, economy, lifecycle and reconciliation **together and inseparably** —
separate `scoring_version` / `economy_version` / `lifecycle_version` columns
could between them describe a season that never existed.

A row carrying a version this build does not know is a **refusal**, not a silent
downgrade.

- `ruleset.py`, `db/schema.py::LeagueSeasonRuleset`, migration `0010_season_ruleset`
- `test_finalpor_wp1_ruleset.py` — 22 PASS

---

## 2. FantasyStakes Score — three terms (WP-7)

```
FantasyStakes Score = Matchup Net + Prop Pool Net − Skunk Fees
```

Skunk is reported as a **positive magnitude** and `net_cents` has already
subtracted it, so a client must not subtract it again.

**Wallet balance does not affect championship position.** Credits determine how
much you can play; competitive results determine whether you are winning. That
principle is inherited unchanged from RC2 and is the reason no accounting field
appears on a competitive row.

- `reports/standings_read_model.py`
- `test_finalpor_wp7_fs_score.py` — 16 PASS

---

## 3. Skunk Fees are optional (WP-2), season-scoped (WP-3), correctable (WP-12)

A Weekly Skunk Fee of **0** is a governed choice: validator, DB CHECK and API
all admit it. A league that sets 0 has **no Points Championship at all** — which
is a different state from having one that is empty.

Skunk is derived **per league-season, per team, through `economy_event`
provenance** — never from the `receivable:` balance, which is neither Skunk-only
nor season-scoped.

### Corrections: REVERSE → RE-DERIVE → RE-POST

A provider correction can change **who was charged**, not just how much. So a
correction reverses the standing posting's own legs (source-faithful — read
back, never recomputed), re-derives the losers from corrected scores, and
re-posts under correction-aware event keys (`gen0`, `gen1`, …). Nothing is
deleted or updated; a correction only appends, and `history()` reads the whole
chain back.

A correction that changes nothing writes **nothing at all**.

- `economy/skunk.py`, `economy/skunk_correction.py`
- `test_finalpor_wp2_skunk_zero.py` — 25 PASS; `test_finalpor_wp12_skunk_correction.py` — 64 PASS

---

## 4. Unused Weekly Minimum → FantasyStakes Championship Pot (WP-4)

At **week** close:

```
min:{team}:{week}  →  fantasystakes_championship:{league}:{season}
```

The forfeiture **is the whole consequence**. No Wallet credit, no `expired_min:`
row, no receivable, no Skunk, no FantasyStakes Score term, and no shortfall
sweep — that last consequence is retired for this era precisely because it would
charge the same GM twice for the same week, against a Wallet the forfeiture had
already emptied.

The credit leg is a **league-level** pot outside the settlement-relevant GM asset
set, which is the mechanism by which the sweep reduces that GM's Current Settle
exactly once and permanently.

**Retired for this era:** `expired_min:` writes, `reconcile_expired_minimum`, the
season-close return to Wallet, and `betting/shortfall_sweep.py`.

- `economy/weekly_minimum.py`, `economy/season_reconciliation.py`
- `test_finalpor_wp4_minimum_sweep.py` — 59 PASS

---

## 5. Championship pots are league-level minted allocations (WP-5) — Model B

A championship pot is a **league-level virtual-credit allocation**. It is not the
sum of per-GM prepaid contributions, and **no GM owes anything because a pot
exists**.

```
championship_issuance:{league}:{season}   −P
<the pillar's pot account>                +P
```

under `CHAMPIONSHIP_POT_MINT_DOOR`, a third door-bound funded-balance exemption
over a third namespace — kept separate from `season_issuance:` and
`bab_issuance:` because Current Settle counts those two against GMs and **must
not** count this one.

### The three pots

| Pillar | Account | Funding |
|---|---|---|
| FantasyStakes | `fantasystakes_championship:{L}:{S}` | minted Base, then **grows** |
| Points | `points_championship:{L}:{S}` | **never minted** — actual Skunk assessed |
| Fantasy Football | `ff_championship:{L}:{S}` | minted once, then **frozen** |

**FantasyStakes Base Pot = Weekly Minimum × Regular-Season Weeks — NOT multiplied
by GM count.** A ten-GM league and a four-GM league on the same stops open the
same Base Pot. This is the arithmetic the retired model got structurally wrong.

**FantasyStakes Current Pot** = Base + unspent Minimum sweeps + approved Top-Off
additions + terminal Prop Pool remainders.

**Fantasy Football Pot** = one commissioner-entered league amount, **may be 0**,
frozen at activation, and it **never accretes** from any source.
`ff_championship_pot_cents` is a **new column**, not a reinterpretation of the
per-GM `championship_contribution_cents`: the same integer cannot mean "each GM
contributes this" for 2025 and "the league's whole pot is this" for 2026.
NULL (unconfigured) and 0 (declined) are stored apart.

**Points Pot** = the Skunk **actually assessed**. The projection (fee × weeks) is
a display figure and is never posted; minting this pillar is refused outright.

**Retired for this era:** the `reserve:{team}` championship contribution and its
sweep, `championship:{league}`, the bare `championship` account, season-less
`skunk:{league}`, the per-GM FantasyStakes contribution (`stage_allocation`
refuses), and the legacy Pool path (a Final POR stamp is now its earliest
marker). **No Final POR season writes to any retired namespace** — asserted by
enumeration.

- `economy/championship_pots.py`, `economy/season_allocation.py`, migration `0012_ff_championship_pot`
- `test_finalpor_wp5_pot_architecture.py` — 104 PASS

---

## 6. An approved Top-Off grows the pot (WP-6)

```
bab_issuance:{L}:{S}                −2X
wallet:{team}                        +X
fantasystakes_championship:{L}:{S}   +X
```

**The GM's obligation is X, not 2X**, and that is structural rather than a
subtraction: both derivations that turn this posting into a number — the cap
(`_issued_from_ledger`) and the obligation (`topoff_issued_cents`) — read the
**Wallet leg only**. The pot leg is a third sibling neither of them sums.

- `economy/top_off.py`
- `test_finalpor_wp6_topoff_pot_leg.py` — 49 PASS

---

## 7. The accepted-wager void (WP-13)

A void says **no contest occurred**. It is not a push — a push is a *result* —
and the two carry different consequences, so they are stored apart
(`voided_wagers`, unique on `bet_id`) rather than collapsed into a Bet status.

- the accepted action **goes on satisfying** that week's Weekly Minimum
- the refund goes to `wallet:{team}`
- `min:{team}:{week}` is **never** restored
- the FantasyStakes Score effect is exactly **0**

The first three are one property of the posting seen from two sides, not a flag
anybody sets. The fourth is why `DOOR_WAGER_VOID` is a member of `VERSUS_DOORS`:
the spend legs then sum to 0 with no open escrow left. Refunding under a door
outside that set would leave the GM permanently −X, charged for a contest that
never happened.

Restoring the Minimum would have been worse than wrong: WP-4 would sweep the
restored balance at week close, so a GM whose game was cancelled would forfeit
Credits they never had a chance to re-wager.

- `economy/wager_void.py`, migration `0013_voided_wagers`
- `test_finalpor_wp13_wager_void.py` — 50 PASS

---

## 8. The FantasyStakes Championship lifecycle: LIVE → FINAL → PAID (WP-8)

**There is no playoff-boundary freeze.** FantasyStakes scoring runs through the
postseason, so the championship is decided by the whole season and the pot is not
knowable until the last contest resolves.

| State | Meaning |
|---|---|
| `LIVE` | scoring still moving, pot still growing |
| `FINAL` | every eligible contest resolved; the pot is authoritative |
| `PAID` | the pot has been distributed |

**There is deliberately no FROZEN state.** It existed to answer "what was the
score at the boundary?" and that question now has no referent.

Every state is **derived from posted state**; none is stored. The finality window
is **season-wide** and its cutoff is derived from `max(week)` across matchups,
challenges and pool instances — not a literal, because a hardcoded season length
is the same class of assumption §18 removes.

The pot is authoritative **only** at FINAL. `pot_cents` (running total) and
`authoritative_pot_cents` (refuses while LIVE) are separate functions so a caller
must choose.

**Retired for this era:** `championship_scoring_gate` (a Final POR season passes
unconditionally), the boundary freeze itself, and with it
`REASON_POSTSEASON_CONTAMINATED`, which becomes unreachable — a postseason result
is no longer contamination, it is the competition.

- `economy/fantasystakes_lifecycle.py`, `economy/fantasystakes_championship_final.py`
- `test_finalpor_wp8_lifecycle.py` — 42 PASS

---

## 9. The three championships

### 9a. Regular-Season Points Championship (WP-9)

Exists **iff** the Weekly Skunk Fee > 0. The pot is the Skunk **actually
assessed**. Ranked on cumulative regular-season Points For, scaled to integer
hundredths so a dead heat is a real equality rather than a float artefact.
Settles only once **every regular-season week is economically final** — a
provider correction lands as a re-finalised matchup, so an unfinalised week is a
week whose Points For can still move.

**§12's provider tiebreak has no source in this build** and is not invented.
`provider_tiebreak_available()` answers `False`; an unbreakable tie is paid as a
dead heat, which is the stated terminal outcome and invents no winner.

- `economy/points_championship.py` — `test_finalpor_wp9_points_championship.py` — 49 PASS

### 9b. FantasyStakes Championship (WP-8)

Paid off the **live season-wide FantasyStakes Score** at FINAL, from the
authoritative pot. No snapshot exists or is written.

### 9c. Fantasy Football Championship (WP-11) — **provider finality BLOCKED**

The podium is the provider's own bracket: champion, the other finalist, and the
winner of the official third-place game (§19's strict rule — exactly the two
championship semifinal losers, affirmatively classified, ambiguity refused).

**No Yahoo postseason bracket classification exists in this build.** Settlement
takes a `ChampionshipTrackState` and refuses unless it affirmatively says the
bracket is complete and decided. It reads no payload, classifies no matchup and
infers no winner from a score. Finality is three-valued — `AVAILABLE`,
`NOT_COMPLETE`, `BLOCKED` — because "nobody has won yet" and "we cannot see the
bracket" are different operational situations and only the second needs action.

**OPEN PRODUCT QUESTION:** a bracket with **no decided third-place game** cannot
settle. §17 requires the pot to be conserved exactly, so a two-name podium cannot
go through the canonical splitter at all. Neither a redistribution rule nor a
stranding rule is stated anywhere, so this fails closed with a named reason
rather than one being invented here. **A ruling is required.**

- `economy/ff_championship_settlement.py` — `test_finalpor_wp11_ff_championship.py` — 49 PASS

---

## 10. One canonical split, and canonical dead heats (WP-10)

**60 / 30 / 10**, one implementation, all three pillars. Not a commissioner
setting.

Percentage flooring leaves a remainder; it goes **in full to the first ordinal
slot**, so the pot is conserved exactly.

**Dead heat.** A tied group occupying ordinal places *p..p+n−1* pools the
allocations of exactly those places and divides them equally. Every GM in the
group is recorded at the **highest** place the group occupies, and the next
finisher takes the place **after** the group.

- tie for 1st → (60+30)/2 = 45 each; next finisher is 3rd
- tie for 2nd → (30+10)/2 = 20 each; no separate 3rd award
- tie for 3rd → (10+0)/2 = 5 each

Equal values are a **real tie** and are never broken. An indivisible cent is
assigned by ascending canonical team id — arithmetic determinism only, never a
competitive tiebreaker.

- `economy/championship_distribution.py` — `test_finalpor_wp10_distribution.py` — 43 PASS

---

## 11. Grand Championship — finalized championship VC (WP-14)

```
Grand Total(GM) = Σ championship VC awarded to that GM, over funded pillars
```

**The 3/2/1 model is retired.** It made every pillar worth the same regardless of
what it was worth, so a league with a $10 Fantasy Football pot and a $200
FantasyStakes pot gave three points for either. Under §20 the pillars are
weighted by what the league actually put into them.

**At least two FUNDED pillars are required.** With one, the Grand Champion is by
definition whoever won that pillar. *Funded* counts a pillar that **ever held
money**, not one that holds money now — a distributed pot holds zero, which is
exactly when the Grand Championship needs to count it. *Funded* is also not
*configured*: a Points Championship exists whenever the fee is above 0 but is
funded only once a Skunk is assessed.

| State | Meaning |
|---|---|
| `PLACEHOLDER` | regular season — **no rows at all**, not rows of zeros |
| `LIVE` | postseason, built from **finalized components only** |
| `FINAL` | every funded pillar has paid |

A pillar that has not paid contributes **nothing** — not a projection, not its
pot, not a provisional podium.

**A tied TOTAL produces co-Grand Champions. There is no tiebreak.** The RC2
model's FantasyStakes-Score tiebreak is retired with the rest of it.

Nothing here posts: every Credit it counts is already in a Wallet.

- `economy/grand_championship.py` — `test_finalpor_wp14_grand_championship.py` — 50 PASS

---

## 12. My Settle / Current Settle (WP-15)

```
Current Settle = settlement-relevant GM assets − GM obligations
```

Derived, never stored, never read from `Wallet.balance`.

**Six concepts stay separate:** Wallet, FantasyStakes Score, Current Settle,
Championship Pots, Top-Off principal, Skunk assessment.

**FantasyStakes Score is not in the accounting object at all.** Accounting is not
competition, and mixing them is how a surface ends up telling a GM their standing
depends on their balance.

Changes for this era:

- **`expired_min:` leaves the asset set.** Never written under the Final POR;
  excluded deliberately rather than by absence of data.
- **The per-GM championship obligation is gone**, structurally — the advance sums
  posted legs and WP-5 stopped posting the reserve leg. A Final POR opening
  allocation moves Current Settle by **exactly zero**, where the retired model
  moved it by −8000 by design.
- **Skunk derives through event provenance**, one source per era and never both.

A **championship POT** is a league account and is nobody's asset. A championship
**AWARD** reaches the GM as a Wallet credit and is counted **once**, by the Wallet
term.

### 12a. Optional external reconciliation mapping (§22)

For leagues that settle up outside FantasyStakes. It is **not a ledger posting,
not a deposit, not payment processing, and not the FantasyStakes Score**. It
writes nothing.

```
dues(GM)  = total MINTED championship VC / |frozen participant field|
owed(GM)  = dues(GM) − current_settle(GM)
```

Equal share, because the pot was allocated by the league rather than bought by
anyone. The field is the **frozen** one — from `SeasonAllocation`, so a GM who
left in Week 9 stays in it and a Week 12 joiner does not.

**Only MINTED Credits attract dues.** A swept Weekly Minimum was already the GM's
own money and was already counted against them; a Top-Off's pot leg rides on an
obligation the GM already carries.

`SUM(owed) == SUM(receivable)`, with awards counted once because they are already
inside the settle figure.

Exact cents; indivisible remainder by ascending participant id.

- `economy/current_settle.py`, `economy/external_mapping.py`
- `test_finalpor_wp15_settle_reshape.py` — 59 PASS

---

## 13. What is NOT settled by this document

- **Yahoo provider authorization state: UNKNOWN.** No credentials in the
  environment. UNKNOWN fails closed everywhere.
- **Yahoo postseason bracket classification: BLOCKED** (PROV-1 / PROV-2). See §9c.
- **A bracket with no third-place game: OPEN.** See §9c. A ruling is required.
- **PostgreSQL parity: NOT RUN.** No `TEST_DATABASE_URL`. Every `*_pg.py` suite is
  unexecuted; each refuses cleanly rather than falling back.

---

## 14. Superseded documents

| Document | Status |
|---|---|
| `spec/RC2_CHAMPIONSHIP_POR.md` | **SUPERSEDED** for `RULESET_FINAL_POR` seasons. Still governs every legacy season, whose championships really were frozen at the boundary, scored on the regular season alone, funded by per-GM contributions and recognised on 3/2/1. |

Superseded documents are **preserved as historical evidence** and are not edited
beyond a supersession header. They remain the correct and complete description of
the seasons they governed.
