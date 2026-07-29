# FantasyStakes — Next-Thread Opener · Rev 2.1

## Where we are
UI/UX Rev 2.1 is committed. My League and My Action are frozen POR. **My Ledger was rebuilt this session to the Opus-ruled Model B accounting** and is POR. Wrap Up and Rules & Settings are baseline, **not yet walked**. No backend code was written; backend gaps remain authoritative.

## The one thing that changed the model
An independent Opus math review ruled **Model B**: the GM's own unresolved escrow (In Play) is a settlement-relevant asset, and `Current Settle = settlement-relevant GM assets − GM obligations`. The **$220 season opening is a −$220 advance obligation**; Top-Offs are additional advances (−$X obligation / +$X Wallet). Buy-in is now part of the Current Settle math, not excluded. Reconciled sample Current Settle = **+$111** (assets $391 − obligations $280). Full ruling + 12 load-bearing invariants are in the continuation package §2.

## Artifacts (branch `remediation/foundation-phase-1`)
- `spec/FantasyStakes_UIUX_Prototype_Rev2_1.html` — canonical prototype (**candidate SHA-256 `8860349d…b86c72d`, PENDING ThinkPad verification**)
- `tools/prototype/index.html` — live copy, byte-identical
- `spec/FantasyStakes_UIUX_Continuation_Package_Rev2_1.md` — full POR + Opus ruling + backend contracts
- `spec/FantasyStakes_UIUX_Next_Thread_Opener_Rev2_1.md` — this file

**Provenance status:** sandbox local commit `353a95c` is **NOT authoritative** (unpushed Claude-sandbox commit). The authoritative Rev2.1 commit SHA and confirmed HTML SHA are **PENDING** the ThinkPad integration + push + fresh-worktree verification.

## Two ways to resume (pick one)
1. **Backend accounting build** — the real work the ruling implies. Build order (continuation §6): **P0** single Ledger authority (retire `Wallet.balance` float, cents-only settlement, funds-check → `balance_of`) → **P1** advance-liability accounts (`advance:{team}`, `skunk_due:{team}`) + opening $220 posting via Door 2 → **P2** Weekly Min lifecycle + Fantasy Week Close + Out of circulation → **P3** own-stake In Play/escrow + wager/refund/void accounting → **P4** Skunk obligations → **P5** Top-Off workflow + advance/cap mechanics → **P6** season-award/championship posting → **P7** authoritative Current Settle reconciliation (last — consumes all accounts above). Money-path gated by Opus math review.
2. **Continue the UI/UX walk** — Wrap Up and Rules & Settings, still baseline. Includes the carried edit: remove the commissioner Weekly-Min-treatment option from Rules & Settings.

## Open ruling still owed
**Top-Off Cap numeric anchor** — the only unresolved product ruling. Do not choose $140 or $220; it's shown "pending" in the prototype. (Championship 60/30/10 and Weekly-Min Fantasy-Week-Close disposition are POR, not open. The canonical Fantasy Week Close *event* is a backend technical spec, not a Fraser ruling.)

## Discipline reminders
Recon before premise (grep live code, not labels). Propose before building. No commit without explicit instruction; no deploy. Opus math review is a hard gate before any money-path code ships. Prototype figures are STATIC; the backend does not yet produce Model-B Current Settle.
