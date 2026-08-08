# L1 — Ledger Primitive MODULE_SPEC

**Status:** DRAFT — awaiting Opus Math Review. No code ships against this spec until certified.
**Gate lines closed:** 4, 5 (foundation).
**Source of truth:** `FantasyBeefs_Launch_Gate_Audit_Findings_Register.md`, Finding 2.8 — this spec formalizes that finding into a buildable primitive. Nothing here contradicts 2.8; it makes 2.8 concrete enough to code against.

---

## 1. The axiom

Every money movement posts **equal-and-opposite entries across named accounts.** The sum of all ledger entries is always exactly zero. Conservation is automatic and total — it survives tabs (credit-funded buy-ins) and payouts (money exiting the system) because every door is a paired posting and an external account absorbs entry and exit.

The old snapshot equation (`sum of buy-ins = sum of wallet balances`) is **not** the definition. It failed the eight-door walk (2026-07-08) because it modeled a cash-funded, closed, no-exit economy while the real design is credit-funded and payout-exiting. Under the ledger, that snapshot becomes a **derived report** — a trial balance taken at an instant — never the source of truth.

**Corollary:** wallet balance is never a stored, directly-mutated number. It is always `balance_of(account) = SUM(entries WHERE account = account)`. There is no code path anywhere that writes `wallet.balance = wallet.balance ± amount`. If such a line exists, it is a defect by definition, not a style preference.

---

## 2. Chart of accounts (seven accounts)

| Account | Scope | Meaning |
|---|---|---|
| **wallet** | per-GM | The GM's spendable BAB balance ($140 visible portion). Sub-accounts or a single account per GM — see open question below. |
| **reserve** | per-GM | The GM's protected $60 championship-pool portion. Same sub-account question as wallet. |
| **receivable** | per-GM | Money owed but not yet paid — the "tab." Exists because buy-in can be committed-not-paid. Clears to `world` when the GM actually pays. |
| **escrow** | per-bet | Holds an open wager's stake between placement and settlement. |
| **championship** | league-wide | The season-end pot. Receives shortfall sweeps and fines; pays out at season end. |
| **skunk** | league-wide | The fine/penalty pot. Separate from championship — different rules, different transparency surface (My Account shows both separately). |
| **world** | external | The system boundary. Buy-ins enter *from* world; payouts exit *to* world. This is what makes the ledger balance even though real money crosses in and out — world is just another account, so the global sum is still zero. |

**Open question for this session (pick before moving to L2):** are `wallet` and `reserve` two separate account rows per GM, or one `wallet` account with an internal `reserve` sub-ledger flag? The Findings Register leaves this as "sub-accounts or one" — recommend **two separate account rows** (`wallet:{team_id}` and `reserve:{team_id}`), because the reserve-ceiling formula (K1, still to come) needs to read reserve's balance independently without parsing a combined ledger, and two clean accounts make that a single `balance_of()` call instead of a filtered query. Fraser to confirm or override.

---

## 3. The postings (every door, worked)

Each door is a single atomic paired posting — one call posts both entries or the whole thing fails. No door ever posts only one side.

### Door 1 — Buy-in, paid upfront
```
debit  world           $200
credit wallet:{team}   $140
credit reserve:{team}  $60
```
Three-way split still nets to zero (one debit, two credits summing to the debit).

### Door 2 — Buy-in, committed-not-paid (tab)
```
debit  receivable:{team}  $200
credit wallet:{team}      $140
credit reserve:{team}     $60
```
The GM has spendable BAB immediately; the debt is tracked as `receivable`, not left unrepresented. When the GM actually pays:
```
debit  world               $200
credit receivable:{team}   $200
```
This clears the tab — a second, later posting, not a rewrite of the first.

### Door 3 — Wager placed
```
debit  wallet:{team}      $amount
credit escrow:{bet_id}    $amount
```

### Door 4 — Wager settled
```
debit  escrow:{bet_id}       $pot_total
credit wallet:{winner_team}  $pot_total
```
For pool bets with multiple winners, `credit wallet` splits across N winners per the remainder rule (Section 4) — the sum of all winner credits must equal `$pot_total` exactly, computed *before* posting.

### Door 5 — Shortfall sweep
```
debit  wallet:{team}        $shortfall
credit championship         $shortfall
```
**Guard (from 2.8, Door 7):** this must never drive a wallet negative. If the wallet can't cover the shortfall, either draw only the funded balance and post the remainder as a `receivable`, or block the sweep and surface it — do not let this posting force a negative wallet. Exact guard logic is a B2 build detail; this spec fixes the *shape* of the posting, not the shortfall-sizing policy.

### Door 6 — Fine / skunk
```
debit  world      $amount
credit skunk      $amount
```

### Door 7 — Championship payout
```
debit  championship   $amount
credit world          $amount
```
This is the door the old snapshot equation couldn't survive — money truly leaves the system. Under paired-posting, it's ordinary: championship debits, world credits, sum stays zero.

---

## 4. The remainder rule (deterministic leftover-cent order)

An unassigned remainder silently breaks conservation — a stranded cent reads as "off by $0.01" and is indistinguishable from a real bug. **Rounding is the bug, not the fix.**

**Rule:** pay each winner the floor amount, then distribute leftover cents one at a time, in a deterministic order, until the payout sums to the pot exactly. Example: $100 ÷ 3 → $33.34 / $33.33 / $33.33 = $100.00 exactly, computed before any posting occurs.

**Ordering key — recommended, pending Fraser confirmation:** a fixed key (e.g. always-lowest-`team_id`) is deterministic but gives one GM a permanent season-long fractional-cent edge. Recommend instead: **order by `(team_id − ISO_week) mod 12`** — still fully deterministic (any two settlements of the same pot in the same week produce identical output), but rotates which GM gets the extra cent week to week, so no one team accumulates the edge over a season. For a friends' league this is a fairness nicety, not a security requirement — Fraser's call whether it's worth the extra line of logic over flat lowest-`team_id`.

---

## 5. What L2 builds on top of this (not in scope here)

This spec only fixes the *law* — accounts, postings, remainder rule. L2 (next session) builds:
- The ledger table schema and the paired-posting function itself (one call, atomic, both-or-neither).
- `balance_of(account)` replacing every stored-balance read.
- The trial-balance function (`SUM(all entries) == 0`, continuously checkable).
- Unit tests: every door above posts and closes to zero; a deliberately one-sided post fails loudly.

L3 migrates the existing money-path code (the six sites already found: `beef_engine.py:568`, `bet_engine.py:94`, `wallet_manager.py:177`, plus settle/pool engines) from direct balance mutation onto these postings.

---

## 6. What Opus Math Review needs to certify

Per the roadmap's L1 Opus gate — issues only, no fixes, Fraser approves each one individually:
1. Do the seven accounts and their postings actually sum to zero across all seven doors above, including the multi-way splits (Door 1, Door 2, Door 4's remainder case)?
2. Does the receivable mechanism (Door 2) correctly represent a tab without double-counting or under-counting GM holdings?
3. Does the remainder rule (Section 4) guarantee exact pot conservation for any winner count, not just the 3-way example?
4. Is the wallet/reserve split (Section 2's open question) actually neutral to conservation, or does either design choice introduce a hidden imbalance risk?
5. Any door, or combination of doors executed out of order, that could leave the ledger in a state where `balance_of()` disagrees with what a GM should actually see?

**No ledger code is written until this certification passes.**
