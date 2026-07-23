# Fantasy Beefs — Merged Canonical Protocol (Build Reference v1)

**Purpose.** This is the single lock-it-down reference for the remaining MVP
build. It adopts the eight-section Official Game Specification v1.0 as the
canonical spine and overrides it in exactly four money-path places with the
rulings settled in the July 18 session. Where the two disagree, this document
states which governs and why.

**Status honesty.** This document is written from the specification documents
and session rulings. Per the existence-check rule, it is NOT "locked" until the
live code is greped against the claims tagged **[PENDING CODE-VERIFY]** below.
That grep is step one of the next build session. Four money-path overrides are
tagged **[OPUS-GATED]** — they are the stated law here but ship only after
Opus Math Review clears each finding individually.

---

## 0. How to read this document

- The canonical spec is Sections 1–8 of the uploaded Official Game
  Specification v1.0 (Core, Game Engine, Ledger, BAB Economy, Simulation
  Engine, System, League Configuration, Additional Protocols). This document
  does NOT restate all of it — it adopts it by reference and records only the
  overrides, additions, and the one reversed decision.
- Nomenclature is the spec's: Simulation Engine (not "odds engine"), Handshake,
  Final Lock, The Adjustment, Locked Challenge, Dynamic Challenge, BAB, Pool
  Bet, Versus Bet.
- Ten divergences were reviewed. This section records the resolution of each.

---

## 1. The ten resolved divergences

### Row 1 — Drift / Dynamic Challenges — **DYNAMIC LIVE AT LAUNCH**

**Decision:** Adopt the spec's Dynamic Challenge model in full. Dynamic
Challenges are live at MVP launch. Odds are priced at the Handshake as a
ceiling, projections may refresh before Final Lock, and The Adjustment reprices
and refunds down to the earliest covered kickoff (spec GE-801+, SIM-601+,
AP-211+).

**This reverses Ruling 1** (the prior "drift doesn't exist, verified in code"
finding). That finding described the *current* code state, not the desired
product. The product decision is Dynamic.

**Consequence, eyes-open:** the current code freezes odds at accept — the
opposite of Dynamic. Building Dynamic means building onto code that presently
does not drift. Three components are pulled onto the critical path:

1. A repricing trigger (watches Yahoo lineups/projections, fires the official
   simulation as kickoff approaches). **[PENDING CODE-VERIFY]** — confirm none
   exists.
2. The Adjustment (derive new stakes, cap at Handshake ceiling, refund excess
   via balanced Ledger postings). The math is certified in the JS Odds
   Calculator (`fairPot = stake / yourProb`); this is a PORT, not a new
   formula. **[OPUS-GATED]**
3. Model-version freeze + informational refreshes (freeze at Handshake, refresh
   against frozen model, store as non-binding, move no money). **[PENDING
   CODE-VERIFY]**

**First build action:** re-grep the three odds write sites and the accept path
before drafting the Dynamic MODULE_SPEC. The rulings are decisions; the code is
truth.

### Row 2 — Versus stake symmetry — **YOUR PLAN (asymmetric derivation)**

**Decision:** Versus stakes are asymmetric. The issuer's stake is the anchor;
the opponent's stake derives from fair odds. The spec sizes each side
independently and caps at the ceiling (AP-213) but never states the derivation
formula. This document supplies it as the law inside the pricing step:

```
fairPot       = stake_issuer / p_issuer
stake_opponent = fairPot * p_opponent
```

The issuer enters only "I'm putting up $X." The app derives and displays the
opponent's stake. No "size me at" toggle (Smarkets-style toggle considered and
rejected). **[OPUS-GATED]**

### Row 3 — Versus rounding / odd cent — **YOUR PLAN (floor-both)**

**Decision:** Both derived stakes are floored to whole BAB cents. The residue
(the sub-cent difference between fairPot and the sum of the two floored stakes)
is **uncollected** — it is never staked, so it never enters the Ledger and
posts nowhere.

```
stake_issuer_cents   = floor(...)         # anchor, already whole cents
stake_opponent_cents = floor(fairPot * p_opponent)
escrow holds exactly stake_issuer_cents + stake_opponent_cents
# no residue leg — the uncollected sub-cent was never funded
```

Rationale: flooring both guarantees the escrow sum never exceeds fairPot, so no
phantom cent is ever funded, and no "who eats it" policy is needed. This
**overrides SIM-807's** deferral to the general remainder rule (which routes
remainders to the Championship Pot — a rule written for POOL splits, not
two-sided versus derivation). Written in as stated law. **Opus is invited to
break it at Math Review** — an adversarial line (e.g. an issuer stake at −150
that does not divide clean) must produce no fractional cent in the Ledger, or
the rule is not tight enough. **[OPUS-GATED]**

### Row 4 — Worst Beat — **DROPPED**

Worst Beat is retired. It is duplicative of the Skunk mechanic (both resolve to
the week's widest-margin loss). The spec's Pool catalog is data (AP-323), so
this is a catalog decision, not a spec conflict. Remaining launch Pool bets:
Biggest Winner, Special Teams Supremacy, The Lineup (rank); Bench Burn
(prediction).

### Row 5 — Weekly-minimum sourcing — **HYBRID**

**Decision:** Adopt the spec's general Weekly Minimum frame (config toggle,
shortfall sweeps to Championship, obligations collect before new wagering —
BAB-301+, AP-231+). Implement "qualifying commitment" (BAB-303) via the
concrete sourcing sequence: accepted-bet spend draws from a per-team-per-week
min pot (`min:{team}:{week}`, funded at weekly release) first; spend beyond the
minimum draws from the wallet. Winnings always land in wallet, never back into
the min (one-directional). Yours is the concrete case of the spec's general
rule — compatible, no conflict.

### Row 6 — Reserve / frozen split — **KEEP YOURS, ADD TO SPEC (genuine gap)**

**Decision:** The spec's Championship funding sources (BAB-402) do not include a
per-team reserve. Add it. At buy-in, a fixed fraction (4/11 = 36.4% of buy-in)
is held in `reserve:{team_id}`, released weekly toward wagerable wallet via a
reserve-ceiling formula, with the remainder held to the Championship Pot at
season end. Commissioner may instead route unspent weekly minimum to a
`frozen:{team_id}` account (distinct from reserve — never releases weekly,
returned only at final reconciliation). This choice is LOCKED at season kickoff,
not adjustable mid-season. Adds to Section 4 (economy) and Section 7 (config).
**[OPUS-GATED]** — money-path.

### Row 7 — Bet floor / stops — **KEEP YOURS, ADD TO SPEC**

**Decision:** Structural bet floor is $1, flat. The spec permits configurable
stake bounds (CFG-603) but does not specify the slider. Add the five-stop
commissioner economy slider (weekly-min → buy-in → wallet → reserve) as the
concrete config values that populate CFG-201/202/603. A separate commissioner
toggle MAY raise the per-bet minimum to $5 (which must divide the weekly-min).
**[PENDING CODE-VERIFY]** — current code defines MIN_BET = 5.00; the $1 ruling
is not yet built.

### Row 8 — Offer expiration — **ADOPT SPEC (aligned)**

60 minutes or the applicable lock, whichever is sooner (GE-303, AP-305). The
spec's "one hour" equals your locked 60-minute ruling. No divergence.

### Row 9 — Pool protocol — **ADOPT SPEC (your ruling, formalized)**

The spec's Pool protocol (GE-1001+, AP-316+) is this session's pool ruling
written into requirement form: every Pool outcome is one GM name or one matchup
of exactly two GM names; no third shape. Prediction vs Rank mechanics.
Self-pick allowed for positive outcomes, blocked for negative (tanking guard),
rank self-inclusion automatic. Adopt verbatim.

### Row 10 — Active cap / duplicates — **ADOPT SPEC**

Max 10 active Versus Bets per GM (GE-406). Economic-duplicate rejection,
including reversed participant order (GE-404/405). New, clean, no conflict.

---

## 2. The canonical spine (adopted by reference)

The following are adopted from the Official Game Specification v1.0 without
change. This document does not restate them; it points to them as governing.

- **Section 1 — Core.** Peer-to-peer, no house, no vig, BAB-only, determinism,
  the seven protocol invariants (INV-001…007).
- **Section 2 — Game Engine.** Wager lifecycle states and transitions
  (Draft → Offered → Accepted → Pending → Final/Push/Void, plus Expired/
  Cancelled), the Versus Engine (Moneyline, Spread, O/U only), the Pool Engine,
  the common Settlement Engine, bye-week and unavailable-entity handling. **Note
  Row 1 override: Dynamic Challenge (GE-801+) is LIVE, not disabled.**
- **Section 3 — Ledger.** Double-entry, immutable postings, the account model
  (Wallet, Escrow, Championship Pot, Skunk Pot, Pool Rollover, Issuance,
  Retirement, Clearing), integer BAB cents, conservation invariants
  (LED-506/507/508). **Add `reserve:{team_id}` and `frozen:{team_id}` per Row
  6.**
- **Section 4 — BAB Economy.** Issuance, wallets, escrow, Weekly Minimum,
  Championship Pot, Skunk Pot, Top-Offs, protocol obligations, season close.
  **Add reserve/frozen mechanic (Row 6) and five-stop slider values (Row 7).**
- **Section 5 — Simulation Engine.** Fair pricing (no vig), model versioning,
  Handshake pricing, informational refreshes, Final Lock, The Adjustment,
  simulation audit. **Row 1: Dynamic path LIVE. Row 2: asymmetric derivation is
  the pricing law. Row 3: floor-both is the SIM-807 rounding law.**
- **Section 6 — System.** Atomicity, idempotency, concurrency, audit,
  authorization, recovery, versioning, isolation. Adopt whole.
- **Section 7 — League Configuration.** Season init, configurable parameters,
  commissioner authority (bounded, no gameplay discretion), season close. **Add
  reserve/frozen config and slider (Rows 6, 7).**
- **Section 8 — Additional Protocols.** Membership, week/season transition,
  Yahoo finalization + stat corrections, pot distributions, Skunk protocol,
  Top-Off workflow, rollover/jackpot completion, the verified-additions list,
  and the explicitly-out-of-scope list (UI, API/DB, notifications, security
  impl, real-money reconciliation, projection methodology, Yahoo API mechanics,
  future wager types). Adopt whole.

---

## 3. Carried-forward mechanics not fully covered by the spec

These are prior decisions/builds that survive the merge and attach to the spine.

- **Skunk Fee** (spec Section 4.7 / 8.2.5 covers the frame): $10/week on the
  widest-margin loser, regular season only, off-wallet obligation, pools to the
  regular-season Points-For leader. Open items: where the obligation sits before
  settlement, and the tie-split remainder rule. **[OPUS-GATED]**
- **Top-Off** (spec Section 4.8 / 8.2.6 covers it): GM-requested,
  commissioner-approved, above-and-beyond wagerable money, reconciled at season
  end. **[PENDING CODE-VERIFY]** — deposit path currently writes off-ledger.
- **Pool rollover / jackpot** (spec Section 8.2.7 covers it): qualifier bets
  roll a persistent jackpot across weeks; terminal sweep to Championship at
  `season_final_week`. Only qualifier/threshold bets are rollover-eligible.
- **Postseason rules** (spec CFG-210 / AP-112 frame): versus requires an active
  matchup for both GMs; pool subjects gate on whether the roster still scores
  real points; no mandatory weekly minimum in playoff weeks; self-pick rules
  hold year-round.
- **~96-bet Pool catalog** (spec AP-323 — catalog is data under the common Pool
  Engine): each catalog entry must resolve to one GM or one matchup, comply with
  the common self-pick/tie/rollover/settlement rules, and introduce no new
  outcome shape. **[PENDING CATALOG READ]** — the full classification file is
  not yet in project; confirm every entry fits the two outcome shapes before
  building.

---

## 4. Build order implied by these decisions

Money-path items are Opus-gated; nothing ships without explicit approval and a
passing Math Review. Stated as sequence, not committed dates.

1. **Re-grep the seam.** Three odds write sites, accept path, current rounding,
   MIN_BET value, deposit path. Confirm the code state the overrides build onto.
   (Rows 1, 3, 7; Section 3 Top-Off.)
2. **Dynamic Challenge MODULE_SPEC** — repricing trigger + The Adjustment
   (asymmetric derivation, floor-both rounding) + model-freeze/refresh. Largest
   item. Opus Math Review on the money-path core. (Rows 1, 2, 3.)
3. **Reserve/frozen + slider** into Section 4/7 economy. (Rows 6, 7.)
4. **Pool Engine** — the launch four, then catalog wiring; dynamic n-way payout
   split (replaces the hardcoded 3-way). (Row 9 + carried items.)
5. **Skunk + Top-Off** ledger paths. (Section 3 carried items.)
6. **Deploy + prod fixture proof** — trial balance closes penny-exact against
   deployed production.

---

## 5. Open flags carried into the next session

- **[PENDING CODE-VERIFY]** Row 1 (three write sites, repricing trigger,
  refresh machinery), Row 7 (MIN_BET = 5.00 vs $1 ruling), Top-Off deposit
  off-ledger.
- **[OPUS-GATED]** Row 2 (asymmetric derivation), Row 3 (floor-both rounding),
  Row 6 (reserve/frozen), Skunk tie-split remainder.
- **[PENDING CATALOG READ]** ~96-bet classification file not in project.
- **Nomenclature bridge:** prior docs say "odds engine" / "escrow.py"; the
  canonical term is Simulation Engine / The Adjustment. Treat old names as
  aliases during the transition.

---

*End of merged protocol v1. This document governs the remaining MVP build once
its [PENDING CODE-VERIFY] tags are cleared by grep. The eight-section
Specification is the canonical spine; Sections 1 and 3 of THIS document record
the only four money-path overrides and the one reversed decision (Dynamic
live).*
