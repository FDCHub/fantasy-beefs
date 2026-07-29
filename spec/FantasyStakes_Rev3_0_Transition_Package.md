# FantasyStakes Rev 3.0 — Transition Package (fresh-thread handoff)

**Purpose:** freeze the current Rev3.0 candidate exactly as-is, bank the new navigation POR, and
carry eight open correction findings into a fresh thread. No HTML was modified in the session that
produced this package. This is documentation only.

---

## 0. Why we are switching threads

The producing thread reached ~85–90% context consumption. Rather than risk a context-loss or
another false-completion event mid-correction, implementation was stopped and this handoff was
produced instead. The eight correction findings below are **not started**; they belong to the fresh
thread with full context.

---

## 1. Exact artifact identity

**Current Rev3.0 candidate (requires correction — NOT final):**
- File: `FantasyStakes_UIUX_Prototype_Rev3_0.html`
- SHA-256: `F8B3EDAC080EB6EB615B8DDD3DAD609A8EFE82F29515A362E23AE372DE5C6CEA`
- Byte size: 130,349

**Frozen baseline (untouched, historical provenance):**
- File: `FantasyStakes_UIUX_Prototype_Rev2_1.html`
- SHA-256: `8860349DB0C02EB8D848B5BC3D552033EF492F72DE3510EC96D031F6DB86C72D`

Rev2.1 remains byte-for-byte untouched. Verified at handoff time: the baseline still hashes
`8860349D…B86C72D`.

The fresh thread must re-verify both hashes before making any change.

---

## 2. Current candidate status (authoritative wording)

- Blocks 1–10 were implemented into a **real** Rev3.0 artifact.
- The prior "Rev3.0 never existed" provenance issue is **resolved**: this artifact genuinely exists
  on disk with the hash above.
- **However**, subsequent independent inspection of the actual HTML found defects that **invalidate
  the earlier claim that the final gate fully passed.** Several assertions in that gate/provenance
  record were false or incomplete.
- Authoritative status: **Rev3.0 exists and is substantially implemented, but independent
  inspection found open defects. It is not final and has not yet passed a corrected final gate.**
- It is a **working candidate, not the frozen/final UI/UX revision.**
- **No Opus review has occurred yet.**

Do not describe this artifact as "passed its gate as built." That claim is withdrawn.

---

## 3. New navigation POR (locked — no HTML change required)

**Locked navigation POR:**

`League · Action · Ledger · Wrap Up · Rules & Settings`

This **supersedes** the prior:

`My League · My Action · My Ledger · Wrap Up · Rules & Settings`

The current Rev3.0 HTML **already renders** `League · Action · Ledger · Wrap Up · Rules & Settings`.
Fraser has made that existing implementation the POR. There is **no nav defect and no HTML change
required** — this is a ruling recorded to confirm the already-implemented navigation.

---

## 4. Open correction findings — carry all eight exactly

**F1 — Canonical Rules drift.** The Rules sheets in Rev3.0 are NOT the final canonical five-sheet
POR verbatim. Known stale/earlier-draft language includes hard-coded `$80`, "all twelve," "Four run
every week," older Pool behavior, and incomplete final Locked/Dynamic treatment. Fresh thread:
compare `RULE_SHEETS` against the frozen canonical five-sheet POR and replace the actual content
accordingly. Do not trust the prior provenance claim that Rules were inserted "verbatim."

**F2 — Impossible Sam-vs-Sam state.** Sam O. is the unified illustrative "you," but My Action shows
a LIVE Versus wager against "Sam O." Correct the opponent (use a real other GM) while preserving the
unified Sam accounting state. Note: the In Play re-derivation (F3) interacts with this — the LIVE
Versus tiles were `$16` (Sam O.) and `$12` (Gridiron); changing the Sam O. opponent must keep the
own-stake accounting coherent.

**F3 — In Play requires re-derivation.** Do NOT assume `$16 + $12 = $28` from two Versus wagers
solves In Play. In Play = ALL accepted, unresolved, own-funded stakes represented in the UI —
including accepted Pool entries where applicable. Pending offer holds (e.g. the `$25` Tara W. sent
offer) remain SEPARATE and are NOT In Play. Re-derive the $28 (or whatever the correct figure is)
from every accepted-unresolved own-funded stake actually shown, and reconcile it consistently across
My League, My Action, My Ledger, and the Commish "GM stakes in play" line for Sam.

**F4 — Stale overlay numbers/timeline.** Normalize ALL overlays/detail sheets to the unified Week 5
/ Sam state. Known stale examples: `Week 8`, `$152 → $192`, `$112 → $152`. **Search the entire
artifact** for legacy values rather than fixing only the named examples. (The main tab strips were
normalized; the detail/overlay `showSheet()` bodies were only partially swept.)

**F5 — Remaining payment-style language.** Remove/rewrite prohibited wording. Known instance:
`Final · paid to wallet` (in `openWon()`). **Search the entire file** for equivalent payment-
processing language (paid, pay, deposit, withdrawal, etc.) on user-facing surfaces.

**F6 — Incorrect pending-offer release destination.** At least one overlay implies held Credits
"return to your wallet" unconditionally when an offer fails. Replace with the governing rule: **the
held stake is released according to its original funding and the governing weekly-account rules.**
Do not imply unconditional Wallet return. (The Rules sheet "Your Credits During an Offer" already
states this correctly; the overlay/challenge-flow copy must match it.)

**F7 — Locked/Dynamic mode propagation overclaim.** `setMode()` changes the composer selector and
the Send button label, but `sendChallenge()` currently just closes the overlay — it does NOT render
a resulting outgoing offer carrying the selected mode. Either (a) implement visible resulting-state
propagation in the prototype, or (b) narrow the UI/provenance claim to what the artifact actually
demonstrates. Do not claim behavior the artifact does not show. **This corrects an overclaim already
present in the current provenance notes.**

**F8 — Lifecycle review appendix stale POR/timeline.** The REVIEW DOCUMENTATION lifecycle appendix
contains stale language. Correct Pool lock wording such as "locks at first kickoff" to **the pool's
own stated lock time**. Normalize `Week 8`/`Week 9` rollover examples to the Week 5 illustrative
timeline. Audit the ENTIRE appendix against current POR, not only the known strings.

---

## 5. Explicitly preserved unresolved item

**Top-Off Cap numeric anchor remains UNRESOLVED.** Do not invent it in the fresh thread and do not
import an older numeric model (e.g. VAL-10). Rev3.0 correctly renders neutral "pending ruling"
language; keep it neutral until Fraser rules the anchor.

---

## 6. Fresh-thread execution order

1. Verify the candidate file hash (`F8B3EDAC…`) and the Rev2.1 baseline hash (`8860349D…`).
2. Reload the governing POR and the frozen canonical five-sheet Rules copy.
3. Correct F1–F8 against the ACTUAL HTML (read the file; do not trust prior narrative).
4. Read back and verify EVERY correction in the file before calling it done.
5. Run a NEW full-file consistency audit — not merely the old 24 checks. The old gate passed while
   defects existed, so the check set itself was insufficient. Expand it (Sam-vs-Sam detection,
   In-Play cross-tab reconciliation, whole-file stale-value sweep, payment-language sweep, overlay
   timeline sweep, lifecycle-appendix POR audit).
6. Render and visually review all five tabs and the relevant overlays.
7. Produce a corrected artifact (new name/version as appropriate) and a truthful provenance record
   written only from what the file proves.
8. ONLY THEN send the complete UI/UX to Opus for independent math/rules/lifecycle/conceptual review.
   The unsent package `SPEC_RS_MODELB_OPUS_REVIEW_PACKAGE.md` exists but is the accounting-model
   review; a full-UI Opus review is the later QA gate.

---

## 7. False-completion safeguard (state prominently in the fresh thread)

**Previous verification assertions are not evidence by themselves.** The next thread must inspect
the actual artifact. A finding is closed ONLY when the corrected file is read back and the file
proves the correction. The prior 24-check gate reported PASS while F1–F8 defects were present —
proof that a green gate is not proof of correctness. Expand the checks and read back every change.

---

## 8. What was and was not done in the producing session

- **Done:** Rev3.0 artifact built (Blocks 1–10), candidate + baseline hashes confirmed, this
  transition package written.
- **NOT done (deferred to fresh thread):** any of F1–F8; any HTML modification; any re-hash; the
  corrected final gate; the full-UI Opus review.
- **No HTML was modified in the session producing this package.** The candidate remains exactly at
  `F8B3EDAC…`.

---

## 9. Reference: other governing artifacts in play

- `FantasyStakes_UIUX_Rev3_0_Review_and_Provenance_Notes.md` — the ORIGINAL provenance notes.
  **Treat as partially inaccurate** (it claims a fully-passed gate and full-verbatim Rules; both are
  contradicted by F1 and F7). Supersede it with a truthful record after corrections.
- `SPEC_RS_MODELB_OPUS_REVIEW_PACKAGE.md` — drafted, unsent; accounting-model review of the
  Model-B Rules & Settings POR and 12-GM dataset.
- Frozen canonical five-sheet Rules POR — the source of truth for F1; reload it in the fresh thread.
