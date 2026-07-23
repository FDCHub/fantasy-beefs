# Fantasy Beefs — Build Sequencing Plan (2026-07-13)

**Purpose:** turn everything decided and verified this session into an ordered, dependency-aware build queue with a recommended launch cut line. This is a planning document, not a MODULE_SPEC — nothing here is a spec, and nothing gets built until its own spec is written and verified against live code per standing discipline.

**Launch target:** August 1, 2026. Sole decision-maker: Fraser.

---

## The core decision this plan is built around (ruled this session)

**Every versus bet is a matched GM-vs-GM pair.** Straight/Spread/O/U get rebuilt from their current single-party (GM-vs-house) form into matched pairs where the accepting GM takes the opposite side of the same line — structurally like Beef. The Lineup gets built (it has no placement path at all today). The `prop` placement path gets removed (retired bet type, still live in code). Existing single-party code is parked, not deleted (post-launch house-mode candidate, same treatment as Stripe).

**Why this is the accelerator, not a from-scratch build:** Beef's challenge/accept/paired-escrow architecture already exists and is certified. The four bet types converge onto that one skeleton; bet type becomes just the winner-evaluator. You generalize one proven mechanism instead of building four.

---

## Verified ground truth this plan rests on (all confirmed via live-code reads this session — no assumptions)

| Component | Status | Implication for the plan |
|---|---|---|
| Beef challenge/accept/paired-row placement | Built, working | The reusable skeleton — the trunk everything hangs off |
| Monte Carlo odds engine (`odds_engine_headless.py` / `monte_carlo.py`) | Built, real (10k-iteration sim), working | Odds-at-acceptance is **free** — already have it |
| Escrow / Flex Stakes / Max Stake Ceiling math | Built & certified — but as **JavaScript** in the Odds Calculator (Rev 1.9) | Reference implementation done; the hard math+audit is behind us |
| `odds_engine.py` — Python port of that escrow math | **Not built** | This is the real net-new backend work for odds-based staking |
| Live odds-drift / stake-update in backend | Doesn't exist | Only needed if odds-based staking ships pre-launch (see cut line) |
| Escrow-close at settlement (Finding 5.9) | Not built — gap confirmed universal across all bet types | Rides on the same skeleton; folds into the matched-bet work |
| Pool bets | Fully ledger-based, clean | Out of scope, untouched |
| `ledger.post()` | Arbitrary-leg, atomic on `session=db` path | Supports every posting shape the plan needs |

---

## RECOMMENDED LAUNCH CUT LINE

| | In for launch | Deferred to fast-follow (post-launch) |
|---|---|---|
| **Matched GM-vs-GM pairs** (Straight/Spread/O/U/Lineup) | ✅ | |
| **Monte Carlo odds at acceptance** (set the line when the bet is matched, like Beef does) | ✅ | |
| **Simple / even-money stake terms** (both GMs stake equal, or a simple agreed amount) | ✅ | |
| **Escrow-close at settlement** (Finding 5.9, all bet types) | ✅ | |
| **`prop` removal, Dockerfile fix, week-claim comment** (small, independent) | ✅ | |
| **Odds-based asymmetric staking** (`odds_engine.py` port — the Flex Stakes / Max Ceiling math) | | ⏭ |
| **Live odds drift before lock** (odds move between offer and Thursday) | | ⏭ |
| **5.6b's 7-ruling stake-matching machinery** | | ⏭ (design done, ships with the port) |

**The reasoning, plainly:** the accelerator is that odds *generation* is already built and matched-pairs reuse Beef's certified skeleton — so you can ship four true peer-to-peer bet types fast. The thing most likely to strand real money if rushed is the odds-based asymmetric stake-splitting (`odds_engine.py` port + drift). That math is certified in JS, but the Python port and its backend wiring haven't been built or reviewed, and this session demonstrated twice that rushing money-path work is where the expensive failures live. Shipping matched-pairs-with-simple-stakes first gets a real, honest, no-house product live by Aug 1; the odds-based staking follows immediately after, built from an already-certified reference rather than crammed.

*This is a recommendation. Fraser rules.*

---

## DEPENDENCY ORDER (what unblocks what)

```
TRUNK (build first, everything hangs off it):
  [A] Generalize Beef's challenge/accept/paired-escrow skeleton
      to carry: a line/spread/total + a bet-type tag + a winner-evaluator hook
        │
        ├─► [B] Straight evaluator      ┐
        ├─► [C] Spread evaluator        │ each is a thin "who won" function
        ├─► [D] O/U evaluator           │ on the shared skeleton
        └─► [E] The Lineup evaluator    ┘
        │
        └─► [F] Escrow-close at settlement (Finding 5.9)
                — rides the skeleton; closes both sides, winner takes pot
                — same fix shape for all bet types once they're matched pairs

PARALLEL (independent, no dependency on the trunk — do anytime, ideally now):
  [P1] Remove/disable prop placement path
  [P2] Dockerfile POSTGRES_PASSWORD → Railway secret reference
  [P3] Commit the week-claim dependency comment (already drafted/applied, uncommitted)
  [P4] Confirm migrate_shortfall_sweep production status — already done this session ✓

FAST-FOLLOW (post-launch, built from the certified JS reference):
  [G] odds_engine.py — Python port of the Odds Calculator's escrow math
        │
        └─► [H] Odds-based asymmetric staking wired into [A]'s acceptance flow
                │
                └─► [I] Live odds drift before lock (if wanted at all)
```

**The critical path is A → (B,C,D,E) → F.** [A] is the long pole — everything else is either a thin evaluator hanging off it, an independent parallel task, or deferred. Get [A] specced and verified first; the evaluators are comparatively small once the skeleton carries a line and a winner hook.

---

## IMMEDIATE NEXT STEPS (in order)

1. **Fire the parallel small items now** — [P1], [P2], [P3]. None depend on anything, all are non-money-path or already-drafted, and clearing them removes clutter and stale-code risk (the `prop` path is a live route to a retired bet type). Each is its own small commit.

2. **Spec [A] — the skeleton generalization — first and carefully.** This is the trunk; getting it wrong is expensive because four bet types plus settlement all sit on it. It gets the full discipline: existence-check the Beef code it generalizes *before* writing rulings (per the standing rule that today's session added), spec it, self-check internal consistency, Opus-review it, verify against live code, then build.

3. **Refold Finding 5.9.** Its "non-beef single-party settlement" sub-case (Rev 4's Section 4b) is now **moot** — once these are matched pairs, they settle like Beef (close both escrows, winner takes pot), so there's no lone-loss question. Pull Section 4b; 5.9 returns to the Beef-shaped escrow-close, now applied uniformly across all matched bet types as step [F].

4. **The evaluators [B]–[E]** get specced once [A]'s skeleton interface is locked — they're thin and can potentially be parallelized (Qwen is suited to self-contained single-function evaluators once the seam is fixed by [A]).

5. **Everything under FAST-FOLLOW stays parked** until launch ships, then [G] (the port) leads, built from the Rev 1.9 JS reference.

---

## What this plan explicitly does NOT do

- It does not rebuild, re-audit, or touch the Odds Calculator (Rev 1.9, production-ready, canonical reference — leave it).
- It does not build odds-based asymmetric staking pre-launch (deferred by the cut line above — Fraser can overrule).
- It does not touch pool bets (confirmed clean) or Stripe (parked, dormant, intact).
- It does not commit or deploy anything without Fraser's explicit word, and no money-path code ships without an Opus pass.

---

## Open questions for Fraser before [A] is specced

| # | Question | Why it matters |
|---|---|---|
| 1 | **Confirm the launch cut line** — matched-pairs + simple stakes in, odds-based staking deferred? | Determines whether `odds_engine.py` is in the critical path or the fast-follow. The single biggest scope lever. |
| 2 | **Simple stake terms — even-money only, or a simple agreed amount both GMs match?** | Defines [A]'s stake model for launch. "GM A stakes $50, GM B matches $50, winner takes $100" is the simplest; confirm that's the launch shape. |
| 3 | **The Lineup — is it launching, or is it the one that slips if time runs short?** | It's the only bet type with zero existing code (no placement path). If the timeline tightens, it's the natural cut before the three that at least have partial scaffolding. |
| 4 | **Does the Monte Carlo line get shown to GMs before they offer/accept** (a "here's the fair line" preview), or only computed at acceptance? | Affects whether a lightweight odds-preview surface is in launch scope or deferred with the rest of odds tooling. |
