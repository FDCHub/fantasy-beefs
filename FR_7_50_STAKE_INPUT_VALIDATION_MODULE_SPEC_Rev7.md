# FR-7.50 — Reject Sub-Cent Stakes at Entry — MODULE_SPEC, Rev 7

**Status:** Verification COMPLETE. **Opus design pass COMPLETE — no
structural gap found.** All findings closed. Ready to build.
**Severity:** **High — live money-path defect on an open route, plus a
false premise under FR-5.6b's certified rounding proof.** Money-path,
Opus-gated.
**Surfaced:** 2026-07-17, by running FR-5.6b's Section 4 verification (q9)
against live code for the first time.

**What this spec does, in one line:** rejects sub-cent stakes at every entry
point that posts to the ledger — closing a live route that silently alters a
GM's stake today (Section 1a), and repairing the false base case under
FR-5.6b's induction (Section 1b).

---

## Revision history

**Rev 7 (current).** Opus's design pass — the first review aimed at the
design rather than the document. **It found no structural gap.** Question 4
(is there a fourth entry point?) came back clean. Promote-over-build,
`ledger/ledger.py` as home, the ordering ruling, and C's inclusion were all
confirmed. Three findings, two closed by execution:
- **E-notation (finding 1) — closed, and the design is more robust than the
  spec claimed.** Opus flagged that `str()` emits E-notation below `1e-4`
  and at/above `1e16`, and that the spec's input-shape reasoning didn't
  cover it — suspecting the check might survive only by luck of ordering
  behind `MIN_BET`. Executed: `Decimal` parses E-notation natively;
  `Decimal('1e-05')` is valid and correctly rejected as not-whole-cents. The
  check never depended on the string being non-scientific. Section 3
  rewritten to say so.
- **Indirect path via `wallet.balance` (finding 3) — closed by grep, and
  the exclusion is now proved.** Opus asked whether `deposit()`'s
  unvalidated float could reach the ledger indirectly, since converted sites
  dual-write to `wallet.balance`. It can't: all ten `ledger_post()` operand
  sets derive from a request param or a `balance_of()` read; the column is
  guard-and-display only. Recorded in Section 2 and Section 5, q7.
- **Induction claim overstated by one layer (finding 2) — corrected.** 1b
  described the defect in storage terms while promising an entry-shaped fix.
  What's restored is "every value reaching `_to_cents()` is provably a whole
  cent," not "floats no longer ride through storage." Section 1b now matches
  Section 3's narrow statement.

**Rev 6.** Three prose findings from Opus's Rev 5 review. Design unchanged.
- **Execution provenance added to Section 1a** — the rounding results now
  show the interpreter (Python 3.13.13) and verbatim repl output, rather
  than reading as possibly derived by hand.
- **Section 1a's harm claim corrected.** It said a rounded-down stake
  "leaves the pot short of what both GMs believe they staked." C is the
  single-party path — no second GM, no shared pot. C's real harm is that
  the stake silently differs from what the GM typed. Pot-short moved to 1b.
- **Sequencing reasoning stated in 1b** — one build, one gate, and why.

**Rev 5.** Two corrections from Fraser's Rev 4 review, both affecting how a
reviewer calibrates:
- **Severity and Section 1 reframed.** Rev 4 buried the live defect in a
  Section 2 note while Section 1 opened on proof structure. A GM can type
  `20.005` on an open route today and be silently charged a different
  amount. That leads now.
- **The rounding mechanism is computed, not asserted.** Direct execution
  shows three distinct mechanisms: `20.005 * 100` → `2000.5` → banker's
  rounding to **2000** (down); `20.015 * 100` → `2001.5` → **2002** (up);
  `20.025 * 100` → `2002.4999999999998` → **2002** (float artifact, not a
  tie). Direction depends on the parity of the neighboring cent. *(Note:
  Fraser's Rev 4 review computed `20.005 * 100` as `2000.4999999999998`; it
  is exactly `2000.5`. The conclusion — rounds down to 2000 — was right; the
  mechanism is banker's rounding, not a float artifact. Kept as a record of
  the correction rather than silently absorbed.)*
- **C-path fixture gains a characterization assertion** proving the defect
  exists before the fix, per this project's bug-and-fix-diverge rule.

**Rev 5.** Two corrections from Fraser's Rev 4 review, both affecting how a
reviewer calibrates:
- **Severity and Section 1 reframed.** Rev 4 buried the live defect in a
  Section 2 note while Section 1 opened on proof structure. A GM can type
  `20.005` on an open route today and be silently charged a different
  amount. That leads now.
- **The rounding mechanism is computed, not asserted.** Direct execution
  shows three distinct mechanisms: `20.005 * 100` → `2000.5` → banker's
  rounding to **2000** (down); `20.015 * 100` → `2001.5` → **2002** (up);
  `20.025 * 100` → `2002.4999999999998` → **2002** (float artifact, not a
  tie). Direction depends on the parity of the neighboring cent. *(Note:
  Fraser's Rev 4 review computed `20.005 * 100` as `2000.4999999999998`; it
  is exactly `2000.5`. The conclusion — rounds down to 2000 — was right; the
  mechanism is banker's rounding, not a float artifact. Kept as a record of
  the correction rather than silently absorbed.)*
- **C-path fixture gains a characterization assertion** proving the defect
  exists before the fix, per this project's bug-and-fix-diverge rule.

**Rev 4.** Three findings from Fraser's Rev 3 review, one of which upgraded
on checking:
- Section 2's exclusion of D/G/H rested on an overclaim ("a door not
  attached to the house"). FR-7.57 showed converted sites dual-write, so the
  float column *is* read live. Exclusion holds on narrower ground: D/G/H
  don't post to the ledger, so they contribute nothing to the induction.
- The `0.1 + 0.2` fixture labeled as a regression guard against a future
  computing caller, not a reachable input.
- **The "no third door" claim was beef-scoped but presented as global — and
  checking it found something worse.** Path C's boundary is clean (q6), but
  C never reaches `_dollars_to_cents()`, and **nothing in the code makes C
  unreachable.** Four live `@app.post` handlers behind the same gate as
  beef. FR-5.13's "zero bets ever" describes history, not an enforced
  invariant. Every prior revision repeated the unreachability claim as fact.
  Corrected throughout. This did not change the design — C was already in
  scope — it changed the argument.

**Rev 3.** Section 5's verification run against live code; all four
questions returned as the design needed. Three corrections made on review of
Rev 2 before verification: Rev 2's Section 6 asserted the `ledger/ledger.py`
home as settled while its own q4 could have invalidated it; Rev 2 over-read
FR-7.12's precedent (it proves import *direction*, not that `beef_engine.py`
and `bet_engine.py` can import down — q2 now answers that directly); and Rev
2's `0.1 + 0.2` ruling rested on an unverified assumption about callers,
which q4 confirmed.

**Rev 2.** Rev 1 claimed two entry points and proposed building a new
Decimal validator, leaving the tolerance question open and contradicting its
own `0.1 + 0.2` fixture. Verification found **eight** entry points and found
the validator **already exists and runs** — `_dollars_to_cents()` in
`api/pool_routes.py`. Rev 2 became a routing spec, not a build spec; the
tolerance question closed by precedent rather than fresh ruling.

**Rev 1.** Initial draft.

---

**Two findings surfaced during this verification are deliberately NOT in
this spec** — see Section 7. Both concern the ledger migration's true
state, not stake validation. FR-7.50 does not depend on either.

---

## 1. The problem, in plain English

**Two problems, and the smaller one is what surfaced first.**

### 1a. The live defect — an open route silently alters a GM's stake

`/bets/straight`, `/bets/spread`, `/bets/over_under`, and `/bets/prop` are
live `@app.post` handlers behind the same `get_buyin_gate` as the beef
routes. Nothing in the code gates, disables, or feature-flags them. They
accept a float stake, validate only `MIN_BET` and `MAX_BET_PCT`, and post
`_to_cents(amount)` = `round(amount * 100)` to the ledger.

A GM typing `$20.005` is not rejected. He is charged **$20.00** — and the
mechanism by which that happens is worse than "rounds down."

**Executed, not derived.** Python 3.13.13, the target interpreter:

```
>>> 20.005 * 100
2000.5
>>> round(20.005 * 100)
2000
>>> 20.015 * 100
2001.5
>>> round(20.015 * 100)
2002
>>> 20.025 * 100
2002.4999999999998
>>> round(20.025 * 100)
2002
```

Read as stake outcomes:

```
$20.005  →  charged $20.00   (banker's rounding, DOWN to even)
$20.015  →  charged $20.02   (banker's rounding, UP to even)
$20.025  →  charged $20.02   (float artifact — genuinely below the tie)
```

Python's `round()` is banker's rounding — exact ties go to the **even**
neighbor. `2000.5` rounds down to 2000 because 2000 is even; `2001.5` rounds
up to 2002 for the same reason. And `20.025 * 100` isn't a tie at all — it's
a float artifact landing just under `2002.5`.

**Three inputs of identical shape, three different mechanisms, and the
direction depends on the parity of a number the GM never sees.**

**The harm on C, stated at its true size.** C is the single-party path — GM
versus house. There is no second GM and no shared pot. The escrow that gets
written is internally consistent with the ledger: $20.00 debited from the
wallet, $20.00 credited to escrow, sums to zero, guards satisfied. **The
defect is that it isn't what he typed.** He asked to stake $20.005 and the
system silently staked something else, with no error, no notice, and a
direction he cannot predict. That's sufficient. It does not need a stronger
framing to justify the fix.

This is a money-path defect on an open route, today. It is not theoretical.

### 1b. The induction premise — FR-5.6b's proof rests on something false

FR-5.6b's rounding design is proved by induction. Every operation in the
escrow lifecycle preserves whole cents, *provided the first number is whole
cents*. Opus confirmed the proof across seven passes (5.6b-29), explicitly
resting it on that base case.

The base case is false.

`issue_challenge()` takes `amount: float`, validates only that it clears
`MIN_BET`, and stores it to a `Column(Float)`. A GM can issue a challenge
for $20.005. The raw float rides unrounded through creation, counter, and
acceptance, and is silently `round()`ed — by the same banker's-rounding
mechanism above — only when it reaches `_to_cents()` at the ledger posting.

Live code (`beefs/beef_engine.py`):

```
amount: float,                                    # :659 — signature

if amount < MIN_BET:                              # :712-713 — sole validation
    raise ValueError(f"Amount ${amount:.2f} is below the minimum ${MIN_BET:.2f}")

amount = amount,                                  # :751 — stored as-is

def _to_cents(amount: float) -> int:              # :75-79 — silent rounding,
    return round(amount * 100)                    #          much later
```

**Precisely what this spec restores — and what it doesn't.** The induction
needs one thing: *every value reaching `_to_cents()` is provably a whole
cent.* That is what gets restored, by rejecting sub-cent stakes at entry.

It is **not** restored by stopping floats from riding through storage —
this spec doesn't do that, deliberately. After it ships, `$20.10` is still
stored as `20.099999999999998` in a `Column(Float)`. Section 3's "what
happens to the value after validation" rules exactly that: nothing, it stays
a float. Once a value is proven within representation error of a whole cent,
`round(amount * 100)` is exact — the artifact cannot change the answer.

The storage problem — floats in money columns at all — is real and belongs
to the integer-cents column migration (Section 7). **This spec makes the
base case true; that spec makes it structurally impossible to violate.**
Earlier revisions described the defect in storage terms ("the raw float
rides unrounded through creation, counter, and acceptance") while promising
an entry-shaped fix. Those are different claims. This one is the accurate
one.

**Where the pot-short harm actually lives — here, not in 1a.** The beef path
is where two stakes meet. Both sides post `_to_cents(effective_amount)`
through the same banker's-rounding mechanism, so both are altered
identically and the pot stays internally consistent. But on a platform with
**no house**, there is no party to absorb a discrepancy: whatever the pot
sums to *is* what the winner collects. A stake that silently became
something other than what two GMs agreed to means the pot they play for
isn't the pot they negotiated. FR-5.6b's Rulings 1/4/5/6 exist precisely to
control that surface — and they are proved on a base case that isn't true.

**One fix closes both.** Reject sub-cent stakes at every entry point that
posts to the ledger: the beef path (repairing 1b's premise) and the
single-party path (closing 1a's open route).

**One build, one Opus gate — and the reasoning, stated rather than left to
be noticed.** 1a is live on an open route right now; 1b is a false premise
under a proof, with no live exploit. Different urgency, same fix, one gate.
That asymmetry is deliberate:

- **Splitting to ship C early buys two Opus reviews of the same function
  move.** The fix is one change — route three entry points through
  `_dollars_to_cents()`. Reviewing half of it, shipping, then reviewing the
  other half doubles the gate cost for one function's worth of work.
- **C's live exposure is real but near-zero in practice.** Private 12-GM
  league, pre-launch, zero bets ever written through any single-party route
  (FR-5.13 — an observation, not an enforced invariant, per Section 2's note
  on C, but an accurate observation nonetheless). The window between "Opus
  reviews this" and "a GM types a sub-cent stake on `/bets/straight`" is not
  a window anyone is standing in.
- **If that changes — if the league goes live before this ships — the
  calculus changes with it.** Recorded here so the decision is revisited on
  evidence rather than inherited as settled.

**The fix already exists in this codebase.** `api/pool_routes.py:59-69`:

```
def _dollars_to_cents(dollars: float) -> int:
    """Exact dollars -> cents. Rejects (never rounds) an amount that isn't
    a whole number of cents — e.g. 10.005 is a bad request, not silently
    rounded to 1000 or 1001 cents."""
    cents = Decimal(str(dollars)) * 100
    if cents != cents.to_integral_value():
        raise ValueError(
            f"{dollars} is not a whole number of cents — amounts must be "
            f"in exact dollars-and-cents (at most two decimal places)"
        )
    return int(cents)
```

Someone hit this exact problem at the pool boundary, solved it correctly,
and documented the intent in the docstring: **rejects, never rounds.** It is
called from exactly one place — `create_pool_config` (`api/pool_routes.py:81`).

This spec's work is to promote that function to the money-path's shared
home and route every other stake entry point through it. Not to design a
validator. To use the one that's been running.

---

## 2. Scope — the eight entry points, verified

| # | Path | Type at entry | Column | Reaches ledger? | In scope? |
|---|---|---|---|---|---|
| A | `issue_challenge()` — beef challenge | `amount: float` | `Float` | Yes, via `_to_cents()` at accept | **Yes** |
| B | `counter_challenge()` — beef counter | `countered_amount: float` | `Float` | Yes, same path | **Yes** |
| C | `_place_bet()` — 4 single-party fns (`place_straight_bet`, `place_spread_bet`, `place_over_under`, `place_prop_bet`) | `amount: float` | `Float` | Yes, via `_to_cents()` | **Yes — see note** |
| D | `deposit()` — wallet funds in | `amount: float` | `Float` | **No ledger posting** — mutates `w.balance` directly | Flagged, not fixed here |
| E | `setup_pool_config()` — pool weekly entry | `weekly_entry_cents: int` | `Integer` | Yes, native cents | **Already correct** |
| F | Season buy-in | `buy_in_cents: int` | `Integer` | Yes, native cents | **Already correct** |
| G | FAAB top-up / transfer | `amount: float` | `Float` | **No L1 ledger posting** — own tables | Flagged, not fixed here |
| H | Commissioner-rule obligation | `amount: float` | `Float` | **No ledger posting** — mutates wallet directly | Flagged, not fixed here |

**In scope: A, B, C.** Every path that carries a wager stake to a
`_to_cents()` call and a ledger posting. Three of these — the four
single-party functions — funnel through one `_place_bet()`, so the actual
edit surface is three functions, not six.

**Note on C — corrected in Rev 4, and it is stronger than earlier revisions
claimed.** Prior revisions said C was "confirmed unreachable in production
(FR-5.13)" and stayed in scope out of caution. **Live code does not support
the unreachability claim.** All four `/bets/*` routes are live `@app.post`
handlers sitting behind the same `get_buyin_gate` as the beef routes.
Nothing in the source disables, gates, or feature-flags them. FR-5.13's
"zero bets ever written" is a deployment/product-surface observation — true,
and worth knowing — but it describes what has happened, not what the code
permits. No test, constraint, or guard enforces it.

**And C is materially weaker than the beef path today.** Verified this
revision: C's API boundary is clean (pass-through, no arithmetic — see
Section 5, q6), but C never reaches `_dollars_to_cents()`. It routes through
`validate_bet_amount()` (`wallet_manager.py:212-226` — `MIN_BET` and
`MAX_BET_PCT` only) and then `_to_cents()` = `round(amount * 100)`
(`bet_engine.py:59`). **A GM typing `20.005` on `/bets/straight` is charged
$20.00** — silently, with no error — precisely the failure this spec exists
to prevent, on a route that is open right now. Section 1a gives the computed
values and the banker's-rounding mechanism behind them; the direction is not
consistently down, it depends on the parity of the neighboring cent.

So C is in scope not despite being dead code, but because it is an open
door with weaker validation than the two this spec hardens. If FR-7.52
retires the path entirely, this coverage becomes moot at that point — not
before.

**Out of scope: D, G, H.** None of them posts to the L1 ledger —
`deposit()` and `release_escrow()` (commissioner rules) mutate
`wallet.balance` directly; FAAB moves float balances on its own tables.
**This spec exists to repair FR-5.6b's whole-cents induction, which is a
proof about the ledger.** A path that never posts to the ledger contributes
nothing to that induction, so validating it buys nothing *for the thing
this spec is fixing*. That is the exclusion's whole ground.

**A narrower ground than earlier revisions claimed, deliberately.** Rev 2
and Rev 3 justified this as "polishing a door that isn't attached to the
house." FR-7.57 (surfaced during this spec's own verification — see
Section 7) shows that framing overclaims: the converted sites **dual-write**,
posting to the ledger *and* still mutating the float column, which is still
read live by at least two routes. So the float column does reach surfaces a
GM sees. The house-and-door metaphor was tidier than the truth. The
exclusion still holds — D/G/H don't post at all — but it holds on the
induction ground above, not on a claim that floats are sealed off from view.

**The indirect path — checked, not assumed (Section 5, q7).** Opus's design
pass asked the question this spec had never asked: if `deposit()` writes an
unvalidated float to `wallet.balance`, and converted sites also write there,
does anything **read** `wallet.balance` and feed it into a `ledger_post()`?
If so, D's float reaches the ledger indirectly, through a door Section 2's
table has no column for.

**It doesn't.** All ten `ledger_post()` operand sets derive their numbers
from either a request parameter (`_to_cents(amount)`) or a ledger read
(`balance_of()` / `_balance_of_in_session()`). Three files read
`wallet.balance` *and* call `ledger_post()` — `bet_engine.py`,
`beef_engine.py`, `settlement_engine.py` — and in all three the column is
used strictly as a guard or a reporting snapshot, never as a posting
operand. The conversion tests assert this directly
(`test_ledger_bet_conversion.py:154-155`,
`test_ledger_beef_conversion.py:158-159`: *"wallet.balance (ORM column)
unchanged — still $1000.00, NOT decremented by this path."*)

**The exclusion is therefore proved, not argued.**

**One nuance the same check surfaced, which is not this spec's problem but
is worth recording:** `validate_bet_amount(amount, wallet.balance)`
(`bet_engine.py:109`) and `if wallet.balance < amount`
(`beef_engine.py:571`) read the stale column as a **gate**. An inflated
`wallet.balance` could let a larger `amount` clear that guard. The posted
value is still `amount`, never the balance — and `post()`'s
`InsufficientFundsError` reads the ledger, so a bet clearing a stale gate
still fails at the posting layer if the ledger can't fund it. FR-7.12 Rev 5
already ruled on exactly this shape: the pre-check improves error quality;
`post()`'s guard is the real defense. Recorded here as a second, evidenced
data point for FR-7.57 (Section 7) — a stale float gating money decisions —
rather than as a gap in this spec.

---

## 3. Design

### `_dollars_to_cents()` moves to `ledger/ledger.py`

Exported alongside `balance_of()`, `_balance_of_in_session()`, and
`_to_cents()`. Imported by `api/pool_routes.py` (which keeps calling it
exactly as today), `beefs/beef_engine.py`, and `betting/bet_engine.py`.
The copy in `pool_routes.py` is deleted.

**Viability — verified, not inferred (Section 5, q1/q2):**

`ledger/ledger.py`'s complete import block is stdlib (`os`, `sys`, `uuid`,
`datetime`), SQLAlchemy, and one first-party import: `from db.schema import
engine, SessionLocal`. **It imports nothing from `api/`, `betting/`,
`beefs/`, `wallet/`, or `admin/`.** It sits below every app layer.

The two modules this spec needs to import it **already do**:
- `beefs/beef_engine.py:70` — `from ledger.ledger import post as ledger_post, _balance_of_in_session`
- `betting/bet_engine.py:36` — `from ledger.ledger import post as ledger_post`

Ten production modules import from `ledger.py` today (`beef_engine`,
`api/main`, `settlement_engine`, `shortfall_sweep`, `bet_engine`,
`pool_engine`, `stripe_connect`, `settlement_report`, `my_account`, and one
migration). Every arrow points into it. No circular-import risk exists for
this move because the dependency edge is already drawn.

**On FR-7.12's precedent, stated accurately:** FR-7.12 Rev 5 ruled
`ledger/ledger.py` the single home for money-path rounding helpers,
consolidated `api/main.py`'s `_to_cents()` copy there, and made `api/main.py`
import it. Git history (`efe0090`) confirms that shipped, including its
deliberate exception (`beef_engine.py`'s pre-existing copy stays local).
That establishes the *direction* of the dependency and that the designated
home functions as ruled — it does **not**, on its own, establish that
`beef_engine.py` and `bet_engine.py` can import from it. Rev 2 over-read it
that way. The q2 evidence above is what actually settles the question; the
precedent is corroboration, not proof.

**`_dollars_to_cents()` moves clean (q5):** its entire dependency surface is
`from decimal import Decimal` — stdlib. It references nothing from
`betting.pool_engine`, `db.deps`, `auth.jwt_auth`, FastAPI, or Pydantic. No
pool config, no session, no request model. `ledger/ledger.py` adds one
stdlib import and the function works unchanged.

### Validation fires at entry, before storage

At each in-scope entry point, immediately adjacent to the existing
`MIN_BET` check:

- `issue_challenge()` — validate `amount` before line 712's `MIN_BET` check
- `counter_challenge()` — validate `countered_amount` before line 980's check
- `_place_bet()` — validate `amount` before `validate_bet_amount()` at
  `bet_engine.py:109`

Ordering within each site: **whole-cents check first, then `MIN_BET`.** A
sub-cent stake is malformed input; a below-minimum stake is a well-formed
request that breaks a rule. Reporting "not a whole number of cents" for
`$20.005` is more useful than reporting it's below $5.00 when it isn't.

### What happens to the value after validation

Nothing. It stays a float in a `Float` column. Once proven within
representation error of a whole cent, `round(amount * 100)` is exact — the
float artifact cannot change the answer. `_to_cents()` continues to do
exactly what it does today, now provably against a value that *is* whole
cents.

Quantizing-and-storing is the integer-cents column migration. See Section 7.

### The float-tolerance question — closed by execution, not by reasoning about input shape

Rev 1 left this open and contradicted itself on it. Resolution:
`Decimal(str(dollars))` is what the running implementation uses, and it is
correct — **for a stronger reason than earlier revisions gave.**

Rev 3 through Rev 6 justified it on *input shape*: "a stake typed into a
form field and serialized through JSON," where `str(20.099999999999998)`
yields `'20.1'` because Python's repr does shortest-round-trip. That
reasoning is true but incomplete, and Opus's design pass correctly flagged
the gap: `str()` switches to E-notation below `1e-4` and at/above `1e16`, so
`str(1e-5)` is `'1e-05'` — and the spec had no stated position on what
happens there.

**Executed rather than reasoned about.** Python 3.13:

```
str(0.0001)   →  '0.0001'      accepted?  no — rejected, not whole cents
str(1e-05)    →  '1e-05'       accepted?  no — rejected, not whole cents
str(1e+16)    →  '1e+16'       accepted?  yes — 10^18 cents, whole
str(0.01)     →  '0.01'        accepted?  yes — 1 cent
```

**The check does not depend on the string being non-scientific.**
`Decimal('1e-05')` is a perfectly valid Decimal; the arithmetic works, and
`to_integral_value()` correctly rejects it because `1e-05 * 100` is
`0.001` cents, not a whole cent. E-notation was never a hazard — `Decimal`
parses it natively. The design is *more* robust than the input-shape
argument claimed, and it does not work "by luck of ordering" behind
`MIN_BET`, which Opus reasonably suspected it might.

`1e+16` accepts because 10^18 cents genuinely *is* a whole-cent value.
Accepting it is correct: **this check governs precision, not magnitude.**
`MIN_BET` and `MAX_BET_PCT` govern magnitude, separately, and that division
of labor is deliberate.

**The known limit, stated plainly rather than buried:** a value produced by
float *arithmetic* upstream — `0.1 + 0.2` → `0.30000000000000004` — does
**not** round-trip, and `_dollars_to_cents()` will reject it. That is a
deliberate consequence, not a bug: a wager stake should arrive from a form
field or an explicit literal, never from accumulated float arithmetic. If
some caller is computing a stake by addition, this validation surfaces
that, and surfacing it is correct. Rev 1's own "done" criterion demanding
`0.1 + 0.2` be accepted was wrong and is withdrawn.

**This is now verified, not assumed (Section 5, q4).** Rev 2 asserted "no
live caller computes a stake by arithmetic" without checking. Live code
confirms it at both in-scope API boundaries:

- `api/main.py:1114-1136`, `/beef/challenge` → `amount = req.amount` —
  passed straight through, no computation, scaling, or rounding between the
  request body and the engine.
- `api/main.py:1175-1190`, `/beef/counter` → `counter_challenge(req.challenge_id,
  req.countered_amount, db, trash_talk=req.trash_talk)` — passed
  positionally, untouched.

The first numeric transformation on a stake is `_to_cents()` inside the
engine, at accept time.

**A further confirmation that tightens coverage — scoped to the beef path.**
`/beef/respond` (the accept route) carries **no amount at all** —
`RespondRequest` holds only `challenge_id`, `accept`, `trash_talk`. The
stake used at acceptance and settlement comes from the stored
`BeefChallenge` record. So **within the beef path**, validating at issue and
counter covers every door by which a stake can be set. There is no third
beef door.

**Path C's boundary, verified separately (Section 5, q6).** All four
single-party routes pass the stake straight through with no arithmetic:
`/bets/straight` (`api/main.py:774-777`), `/bets/spread` (:795-798),
`/bets/over_under` (:816-819), `/bets/prop` (:837-840) — each hands
`req.amount` directly to its `place_*` function. So C's boundary matches
B's. **But C is not covered by the beef-path argument above** — it is its
own door, reached through `_place_bet()`, and it is in scope for exactly
that reason. See Section 2's note on C.

---

## 4. Design options

| Name | Issue Summary | Options | Recommendation & Reasoning |
|---|---|---|---|
| **Build vs. promote** | Rev 1 proposed designing a new validator. One already exists and runs. | (a) Promote `_dollars_to_cents()` to `ledger/ledger.py`, route all in-scope paths through it. (b) Build a new `_validate_stake()` helper. (c) Inline the check at each site. | **(a).** It's written, correct, documented, and in production at the pool boundary. Building a second one is how two money-path rounding rules end up in two files drifting apart — the exact reasoning FR-7.12 used, and which this session verified held. |
| **Its home** | Where the promoted function lives. | (a) `ledger/ledger.py`, exported. (b) A new `money.py` / `validation.py`. (c) Leave in `pool_routes.py`, import from there. | **(a), now verified viable (q1/q2).** `ledger.py` imports nothing from any app layer, and `beef_engine.py:70` / `bet_engine.py:36` already import from it — the dependency edge this spec needs is already drawn, so no cycle is possible. FR-7.12's designation corroborates but does not prove this; the import surface does. (c) would make an API route module a dependency of two engines — backwards. |
| **Check ordering vs. `MIN_BET`** | Both fire at entry; which first. | (a) Whole-cents first, then `MIN_BET`. (b) `MIN_BET` first. | **(a).** Malformed before rule-breaking. `$20.005` should report the precision problem, not a minimum it actually clears. |
| **Single-party paths (C)** | Four live `@app.post` routes that post `_to_cents(amount)` to the ledger with no whole-cent validation. Prior revisions called them "confirmed unreachable (FR-5.13)." | (a) In scope. (b) Out of scope — dead code, FR-7.52 may retire them. | **(a), and Rev 4 corrects the reasoning.** Earlier revisions kept C in scope *despite* believing it unreachable. That premise is wrong: nothing in the code gates these routes, and FR-5.13's "zero bets ever" is an observation about history, not an enforced invariant. Worse, C silently rounds a sub-cent stake today (`validate_bet_amount()` → `_to_cents()` = `round(amount * 100)`, no `_dollars_to_cents()`), which is the exact defect this spec repairs. C isn't in scope out of caution — it's in scope because it's an open door with weaker validation than the two being hardened. |
| **Non-ledger money paths (D, G, H)** | Three paths take float amounts and move real money without touching the ledger. | (a) Out of scope, flagged. (b) Fold in — they take stakes too. | **(a).** They bypass the ledger entirely, which is the July 14 audit's incomplete-migration finding, not a rounding finding. Validating whole cents into `w.balance = round(w.balance + amount, 2)` improves nothing that matters. Fold them in when they're migrated, on that spec, not this one. |
| **`MIN_BET` as a float (FR-7.55)** | `MIN_BET = 5.00`, float dollars, compared against stakes this spec makes whole-cent-exact. | (a) Convert to `MIN_BET_CENTS = 500` here. (b) Defer to the integer-cents column migration. | **(b), per FR-7.55's ruling this session.** `5.00` is exactly representable, and every value compared against it will be whole-cents-validated once this lands — no live bug. It's the same "float shouldn't be here" problem the column migration exists to solve; doing a piece of it here splits one migration across two specs. |

---

## 5. Verification — COMPLETE

Two passes have been run against live code. Both are closed. Nothing
remains to verify before Opus review.

**Pass 1 — the entry-point sweep (produced Rev 2's scope).** Results are
Section 2's table. Headline: eight entry points, not the two Rev 1 claimed;
`_dollars_to_cents()` already exists and runs at the pool boundary; no
Pydantic `decimal_places` or `multiple_of` constraint exists on any amount
field anywhere.

**Pass 2 — the design's own assumptions (produced Rev 3).** Four
questions, each aimed at something Rev 2 asserted without checking.

| # | Question | Result |
|---|---|---|
| q1 | Does `ledger/ledger.py` import from app modules — i.e. would importing it back create a cycle? | **No.** Stdlib + SQLAlchemy + `db.schema` only. It sits below every app layer. |
| q2 | What is `ledger.py`'s real import surface — who imports it, in which direction? | **Ten production modules import it; it imports none of them.** Critically `beefs/beef_engine.py:70` and `betting/bet_engine.py:36` — the two this spec touches — already do. |
| q3 | Is `deposit()` a converted or unconverted direct-mutation site? | **Unconverted.** Mutates `w.balance` directly, no ledger posting; `wallet_manager.py` imports nothing from `ledger.ledger`. **Contradicts the L1–L3 completion record.** Out of scope here — see Section 7 / FR-7.56. |
| q4 | Does float arithmetic touch a stake between the API boundary and the engine? | **No.** `amount = req.amount` at `/beef/challenge`; `req.countered_amount` passed positionally at `/beef/counter`. `/beef/respond` carries no amount at all. |
| q5 | Does `_dollars_to_cents()` carry pool-specific dependencies? | **No.** `from decimal import Decimal`, stdlib, nothing else. |
| q6 | Does float arithmetic touch the stake on the four single-party routes before `_place_bet()`? | **No.** `/bets/straight` (`api/main.py:774-777`), `/bets/spread` (:795-798), `/bets/over_under` (:816-819), `/bets/prop` (:837-840) — each passes `req.amount` straight through. **The same read established C never reaches `_dollars_to_cents()`** — it uses `validate_bet_amount()` then `round(amount * 100)`, so it silently rounds a sub-cent stake today. It also established that nothing in the code gates these routes. See Section 2's note on C. |
| q7 | Can an unvalidated float entering via `deposit()` reach a ledger posting **indirectly**, through `wallet.balance`? | **No.** All ten `ledger_post()` operand sets derive from a request param (`_to_cents(amount)`) or a ledger read (`balance_of()`). The three files that read `wallet.balance` *and* post (`bet_engine`, `beef_engine`, `settlement_engine`) use it only as a guard or reporting snapshot. Asserted directly by `test_ledger_bet_conversion.py:154-155` and `test_ledger_beef_conversion.py:158-159`. **This proves Section 2's D/G/H exclusion rather than arguing it.** |
| q8 | Does `Decimal(str(x))` have a failure mode on E-notation inputs (`str(1e-5)` → `'1e-05'`)? | **No.** `Decimal` parses E-notation natively; `to_integral_value()` correctly rejects `1e-05` as not-whole-cents. The check never depended on the string being non-scientific, and does not work "by luck of ordering" behind `MIN_BET`. See Section 3. |

**What this settles.** Rev 2's three load-bearing assumptions — that
`ledger/ledger.py` is a viable home, that `_dollars_to_cents()` moves clean,
and that no caller computes a stake by arithmetic — are each now confirmed
against quoted live code rather than inferred from a document label or a
precedent's shape.

**One open item deliberately not chased:** Rev 2's original q3 asked
whether `_place_bet()` is the single funnel for all four single-party entry
points. Pass 1 established that it is (`place_straight_bet`,
`place_spread_bet`, `place_over_under`, `place_prop_bet` all funnel through
`_place_bet(..., amount: float, ...)` at `bet_engine.py:95-98`). Stated here
so its absence from Pass 2's table isn't read as a gap.

---

## 6. What "done" looks like

- `_dollars_to_cents()` lives in `ledger/ledger.py`, exported, single copy.
  `api/pool_routes.py`'s copy deleted; it imports instead. Its behavior at
  the pool boundary is unchanged — a regression test proves that.
- `issue_challenge()`, `counter_challenge()`, and `_place_bet()` each call
  it before their `MIN_BET` check.
- Fixtures, each asserting the specific outcome:
  - `20.005` → raises, at all three entry points, before storage
  - `20.00` → accepted
  - `20.10` → accepted (the float-artifact case: stored as
    `20.099999999999998`, must not be rejected)
  - `0.1 + 0.2` → **raises**, deliberately (see Section 3's stated limit).
    **Guards a future computing caller, not a live one** — q4 confirms no
    caller computes a stake by arithmetic today. The fixture pins the
    rejection behavior so a later refactor that introduces arithmetic fails
    loudly instead of silently rounding. Unlike `20.005` and `20.10`, this
    input is not reachable by a GM; it is a regression guard.
  - **`20.005` on `/bets/straight` → raises.** This is the C-path fixture,
    and it asserts a behavior change. **Paired with a characterization
    assertion, run before the fix and discarded after:** confirm that today
    the same input posts **2000 cents** to the ledger — no error, GM charged
    $20.00 for a $20.005 bet. Without it, the fixture proves the fix works
    but not that the defect was real, and this project's own rule is that
    fixtures must use data where the bug and the fix diverge. Section 1a's
    computed values are what this assertion pins.
  - `MIN_BET` boundary still enforced independently, and reports the
    minimum — not a precision error — for a well-formed `$4.99`
  - Pool config path unchanged: `10.005` still rejected via the moved function
- Opus Math Review, issues-only, before any code.

**Not a completion criterion, but owed at session close:** FR-5.6b's
Section 4 q9 is now answered — its base case was **false**, and this spec is
what makes it true. The Rev 7 document currently reads as though the base
case is merely unverified rather than known-broken. That correction is
document hygiene for the session-close pass, not a gate on this spec's
build. Recorded here so it isn't lost.

---

## 7. Explicitly not in this spec

- **The integer-cents column migration** (`amount` / `countered_amount` /
  every `Column(Float)` on the money path → integer cents; float never
  enters). Correct long-term shape, matches the project's stated
  integer-cents-end-to-end invariant. Touches every read and write of
  multiple columns across every consumer. **Its own spec.** This spec makes
  the base case true; that spec makes it structurally impossible to
  violate. `MIN_BET → MIN_BET_CENTS` (FR-7.55) belongs there.
- **The three non-ledger money paths (D: `deposit()`, G: FAAB, H:
  commissioner rules).** They take float amounts and move real money
  without any ledger posting. **This is the incomplete ledger migration
  from the July 14 Code-Plan Reconciliation Audit, still open.** Named here
  so this spec's coverage isn't mistaken for completeness: after FR-7.50
  ships, three money-moving paths still accept unvalidated floats. That is
  known, deliberate, and someone else's spec.

- **FR-7.56 and FR-7.57 — surfaced by this spec's verification, held
  outside it and outside Opus review.** Both concern the ledger migration's
  true state; neither involves arithmetic, postings, or rounding, so the
  Math Review Protocol has no purchase on them. They are Fraser's rulings,
  recorded here only so the trail from this verification to them is visible:
  - **FR-7.56** — `deposit()` is an unconverted direct-mutation site
    (`wallet_manager.py:133-150`, `w.balance = round(w.balance + amount, 2)`,
    no ledger import in the file). The L1–L3 record states all three
    direct-mutation sites were converted. One of those two records is wrong.
    FR-7.12 Rev 5 separately notes `wm_deposit()` "still writes it until
    FR-7.28 lands" — so a *second* record already contradicts the first.
  - **FR-7.57** — "converted to the ledger" appears to have meant
    *dual-write*, not migration. `beefs/beef_engine.py:596-600`, verbatim:
    *"the Transaction row below stays alongside this for now —
    `wallet.balance` is still what `api/main.py`'s `/faab/wallet/{team_id}`
    route reads, so both are written in parallel until that route is
    migrated too."* Converted sites post to the ledger **and** keep
    mutating the float column. Correctness is not threatened today — the
    ledger is authoritative and its guards hold — but the dual-write has
    outlived its stated one-route justification (FR-7.12 Rev 5 already
    excepted a second reader, `/wallet/deposit` at `api/main.py:1002`).
- **The three straggler `_to_cents()` copies** (`bet_engine.py`,
  `shortfall_sweep.py`, `beef_engine.py`). Git history confirms all three
  predate FR-7.12, which scoped itself narrowly and honored its own stated
  exception. Consolidating them is real cleanup with a known cause — low
  severity, no blocker, its own small spec. (FR-7.54, downgraded this
  session after the history check.)
- **`CounterRequest.countered_amount`'s missing `gt=0`** (FR-7.53). One
  line, same file, tempting to ride along. Ruled separately this session:
  different problem, different failure mode.
- **FR-5.6b's Rulings 1/4/5/6.** Untouched. This spec restores the premise
  they were proved on; it does not revisit them.
- **The odds engine port.** Downstream of this — it derives stakes *from*
  `origStake`, so `origStake` must be trustworthy first.
