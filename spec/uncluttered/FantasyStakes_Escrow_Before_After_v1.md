# FantasyStakes — FSR-023 Escrow Restatement · Before / After

**Date:** 2026-08-28
**From:** Action v22 · Standings + Wrap Up v6 · Account + Gear v23 · Fixture v2
**To:** Action v23 · Standings + Wrap Up v7 · Account + Gear v24 · Fixture v3

---

## Headline

| | BEFORE | AFTER |
|---|---:|---:|
| Wallet | Ŧ138 | **Ŧ94** |
| Weekly Min | Ŧ0 | Ŧ0 |
| In Play | Ŧ37 | **Ŧ81** |
| FantasyStakes Score | +Ŧ65 | +Ŧ65 |
| Final Reconciliation | Ŧ285 | Ŧ285 |

## Why

**Ŧ44 moved from Wallet into previously omitted or mis-stated Versus escrow. Total holdings
did not change.**

The Action board was showing four live Versus commitments for Pain Sanders. The Ledger
recorded two of them, one at the wrong amount:

| Commitment | Action lifecycle | Should hold | Ledger held | Delta |
|---|---|---:|---:|---:|
| Hank Williams | accepted, Pain is issuer | Ŧ20 | Ŧ20 | — |
| Dolly Parton | **pending outgoing**, Pain is issuer | Ŧ20 | Ŧ16 *("accepted exposure")* | +Ŧ4 |
| Reba McEntire | counter-pending, Pain is original issuer | Ŧ20 | **nothing** | +Ŧ20 |
| Loretta Lynn | accepted, Pain is issuer | Ŧ20 | **nothing** | +Ŧ20 |
| Prop Pool ticket | funded | Ŧ1 | Ŧ1 | — |
| | | **Ŧ81** | **Ŧ37** | **+Ŧ44** |

Escrow was understated by Ŧ44, so Wallet was overstated by exactly Ŧ44. The money was
always committed; the Ledger simply did not say so.

## Conservation

```
BEFORE                          AFTER
Wallet             Ŧ138         Wallet             Ŧ 94   −Ŧ44
Remaining weekly   Ŧ 30         Remaining weekly   Ŧ 30
Championship       Ŧ 80         Championship       Ŧ 80
Versus escrow      Ŧ 36         Versus escrow      Ŧ 80   +Ŧ44
Pool committed     Ŧ  1         Pool committed     Ŧ  1
                   ─────                           ─────
Total holdings     Ŧ285         Total holdings     Ŧ285   unchanged
```

Nothing was created or destroyed. This is a restatement of where the GM's own capital
already sat.

The Skunk Pot (Ŧ10) sits outside this table in both columns: under LED-346 contributed BAB
stays in the Pot until an authorized distribution, so it has left the GM's holdings even
though it still counts once in the FantasyStakes Score.

## What did not change, and why

- **FantasyStakes Score stays +Ŧ65.** Escrow postings move value between the GM's own
  accounts (Wallet → Active Bet Escrow). They are non-score-bearing and never touch Settled
  Counterparties or the Skunk Pot. Asserted by check F16.21.
- **Final Reconciliation stays Ŧ285.** It is Season Allocation (Ŧ220) + FantasyStakes Score
  (+Ŧ65) + championship nets (Ŧ0) + Top-Offs (Ŧ0). None of those inputs is a function of
  escrow.
- **Weekly Min stays Ŧ0.** Qualifying commitments actually *rose* from Ŧ37 to Ŧ41 — the
  Loretta acceptance now counts — but the Weekly Minimum is Ŧ10, so the remainder was
  already floored at zero and stays there.

## A distinction the previous release did not make

IN PLAY and Weekly Minimum qualification are **not** the same quantity, and the previous
release asserted that they were:

| | Composition | Total |
|---|---|---:|
| **IN PLAY** | every held commitment — accepted + pending issuer + counter-pending issuer + funded pool | **Ŧ81** |
| **Weekly Min qualifying** | governed qualifying gameplay only — accepted Versus + funded pool | **Ŧ41** |
| Difference | Dolly Ŧ20 (pending) + Reba Ŧ20 (counter-pending) | Ŧ40 |

Committed capital is not automatically qualifying gameplay. A pending or counter-pending
offer ties up money without yet being action that satisfies the weekly minimum.

## The Reba case

Reba's active proposal is the **counter** at an Anchor of Ŧ26. The escrow held is the
**original** Ŧ20 Anchor, because a counter creates a new immutable proposal and moves no
money — the original issuer's escrow-at-issue is what remains held, and the counter's
Anchor has escrowed nothing from anyone.

Check F16.14 asserts all three facts: the escrow equals the original Anchor, it does not
equal the counter Anchor, and the fixture still exercises two genuinely different values so
the check cannot pass vacuously.

## Verification

150/150 checks pass (was 120/120), including 30 new FSR-023 checks that derive expected
escrow from Action lifecycle state and drive it through the canonical schedule, the Ledger,
and both **rendered** strips.

```
node spec/uncluttered/FantasyStakes_Remediation_Reconciliation_v2.js
```
