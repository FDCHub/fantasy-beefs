# FantasyStakes — Session Transition Package
## UI/UX Discovery Phase Close · 2026-07-29

**Branch:** `remediation/foundation-phase-1`
**HEAD at session start:** `ff70f56572411a134a6e2e84ae98a086bb01b8dc`
**Thread type:** UI/UX correction and discovery. No backend work. No deployment.
**Authorizes nothing.**

Six parts, per standing rule: opener · architecture · findings register · Master Plan ·
handoff · git check.

---

# PART 1 — Next-thread opener

> **Thread purpose:** return to the authoritative backend specification and development
> sequence. The UI/UX discovery phase is closed. Do not reopen it.
>
> **Read first:** `spec/REV3_1_UIUX_POR_REGISTER.md` and
> `spec/MECHANICS_VALIDATION_PROGRAM_Gate1_Staged.md`. Both are POR. Neither authorizes a build.
>
> **Verify before any work:** branch `remediation/foundation-phase-1`; HEAD and
> `origin/remediation/foundation-phase-1` agree; working tree state matches Part 6 below.
>
> **Binding build order, unchanged:**
> Security remediation → FR-8.7 closure → controlled foundation deployment → FR-AC-ISO-1 gate →
> Spec 2 → Spec 3A → Spec 3B → Spec 5 → Spec 4.
>
> **CORRECTION — read before acting.** An earlier draft of this opener named FR-SEC-DB-2 as the
> next action. **That was wrong and is withdrawn.** FR-SEC-DB-2 was **CLASSIFIED on 2026-07-25**
> (`Findings_Register_v17.md` §19.2): `reseau.proxy.rlwy.net:54032` answers HTTP, not PostgreSQL.
> The Railway proxy port was recycled to a third party. **Do not probe that address.** No
> credential was transmitted; `SSLRequest` precedes authentication.
>
> **Immediate next action:** Stage A items independent of the paused rotation.
> **A3 · FR-SEC-DB-5** — classify `C:\FantasyBeefs_Backups\` · `fantasy-beefs_9ff096b.zip`; two
> commands settle whether `.git` is present. Then **A4 · FR-7.37** — delete the abandoned Yahoo
> app (key prefix `dj0yJmk9VDJSWHpm`, proven distinct from the live `dj0yJmk9Y0FH`), ruled
> 2026-07-16 and never executed. **A4 has an open severity input:** whether `FDCHub/fantasy-beefs`
> is public.
>
> **FR-SEC-DB-1 is not unblocked by DB-2's classification.** Rotation blocks on three
> prerequisites, none complete: second durable passphrase copy · desync response procedure Rev 4 ·
> rehearsal execution and teardown. Phase C stays gated. Option B governs the rotation order.
>
> **Full detail, including four document conflicts and the CF-A…CF-H carry-forward register:**
> `spec/BACKEND_TRANSITION_BRIEF_2026-07-29.md`.
>
> **Then:** FR-8.7 closure — test 6d (7-scenario crash/concurrency taxonomy), settled-reader
> grep, review package, final review, migration execution, deployment confirmation.
>
> **Carried into the Spec 2 Opus package when it runs:** the escrow-at-issue regression set in
> §3 of the Mechanics Validation Program. Targeted only. Do not reopen unrelated conclusions.
>
> **Standing rules:** propose before building · recon before premise · read live code not labels ·
> no commit without explicit instruction · no deploy without explicit
> `railway up --service fantasy-beefs` · Opus math review is a hard gate on money-path code ·
> integer cents everywhere · never `git add .` on a money-path commit.
>
> **Do not rebuild the UI.** UI-VS-1, UI-COMMISH-TOPOFF-1, and UI-LEDGER-1 are recorded and
> deferred. Rev3.1 authorization comes separately.

---

# PART 2 — Architecture change spec

No diagram regenerated this session. Recorded as a change spec against
`fantasy_beefs_architecture_print_v14.html`, for folding into v15.

### Backend — no change
No backend code, schema, migration, or deployment touched. All percent-complete badges on
backend nodes carry forward unchanged.

### UI/UX layer — changes

| Node | Change |
|---|---|
| **Rules sheets** | `RULE_SHEETS` replaced wholesale with the canonical five-sheet POR. All five sheets now `Canonical POR`. Mixed `authoritative / draft / pending` status tags retired. **Badge: was mixed-status, now canonical-content · not final artifact.** |
| **Versus interaction** | Nested-sheet model marked **superseded** by UI-VS-1. Current implementation remains in place. **Badge: superseded-pending-rebuild.** |
| **Commish surface** | New node required — Top-Off approval queue. **Badge: 0% — specified, not built.** |
| **Ledger presentation** | Seven-group hierarchy marked superseded by UI-LEDGER-1's three layers. Accounting model unchanged. **Badge: superseded-pending-rebuild.** |
| **Pool lifecycle surfaces** | Dependency labels required — `SUPPORTED AFTER SPEC 4` alongside the existing `SUPPORTED AFTER SPEC 5`. |
| **Dynamic / pricing surfaces** | Dependency labels required — `SUPPORTED AFTER SPEC 3A/3B`. |

### New cross-cutting element
**UI dependency register** — §5 of the Mechanics Validation Program. Every prototype surface
mapped to its governing spec: AUTHORITATIVE · PARTIAL · PENDING · RULED. This is the mechanism
preventing UI depiction from being mistaken for backend authority. It belongs on the v15 diagram
as a legend, not a node.

---

# PART 3 — Findings register update

### Closed this session

| Ref | Finding | Evidence |
|---|---|---|
| **F1** | Canonical Rules drift | `RULE_SHEETS` replaced wholesale. All five sheets evaluated at runtime. `all twelve` 0 · `Four run every week` 0. Six canonical anchors present |
| **F2** | Impossible Sam-vs-Sam | Opponent → `Lena F.` at lines 554, 555, 636. Amounts untouched. Six `Sam O.` survivors all legitimate |
| **F5** | Payment-style language | `Final · paid to wallet` → `Final · settled · Credits posted to Wallet`. Old string 0 |
| **F6** | Pending-offer release destination | Unconditional wallet return replaced with the governing release rule. Now matches the Rules sheet. `$20` → `$25` to match the tile |
| **F8** | Lifecycle appendix pool lock | `locks at first kickoff` → `locks at the pool's stated lock time`. Old string 0 |
| **F3** | In Play components | Amounts ruled illustrative, not POR. Rebuild sets Versus `$24` + Pool `$4` = `$28` |
| **Duplicate Pool identities** | Same pool in mutually exclusive states | COMPLETED examples → `Highest Scoring Team` (SETTLING) and `Biggest Winner` (terminal). Both added to `POOLQ` |
| **Top-Off stale Wallet** | `$152 → $192`, `$112 → $152` | Removed. Replaced with `Posted to Wallet +$40`. No fabricated balance pair |
| **Rollover week residue** | Wk 7/8/9 in three places | Normalized to the Week 5 timeline |
| **A4 Skunk** | Fixed-vs-configurable, pot-vs-no-pot | **RULED.** Fixed `$10`, no in-season pot, no funded holding account. FR v12.2 §I-3 superseded on those points |
| **A8 / A9** | Gate 1 duplication | **CLOSED.** Gate 1 staged. G1-a *is* the queued Spec 2 review |
| **UIL1-M1** | Layer 2 Wallet composition | **RULED.** Explain the balance, don't prove it. One arithmetic proof, at Current Settle |

### Open — recorded, deferred

| Ref | Finding | Status |
|---|---|---|
| **UI-VS-1** | Unified Versus workspace | POR RECORDED · NOT IMPLEMENTED · Rev3.1 |
| **UI-COMMISH-TOPOFF-1** | Commissioner Top-Off surface missing | POR RECORDED · NOT IMPLEMENTED · Rev3.1 |
| **UI-LEDGER-1** | Ledger hierarchy simplification | POR RECORDED · NOT IMPLEMENTED · Rev3.1 |
| **F7** | LOCKED/DYNAMIC mode propagation | OPEN · built inside UI-VS-1 · truthful `PROTOTYPE LIMIT` comment in place |
| **Future-week rows** | Wk 6/Wk 7 settled results at Week 5 | Invalid sample data. Must not survive Rev3.1. No repair pass now |
| **Top-Off Cap anchor** | Numeric anchor | UNRESOLVED · standing · do not invent |

### New process finding

**FR-UIUX-PROV-1 — the prototype ran ahead of its specification.** Roughly half the surfaces the
artifact renders — all Pool lifecycle, Dynamic mode, stake economics, Weekly Min lifecycle — have
no authoritative governing spec. The prior gate passed while eight defects were live, in part
because there was no spec to check against. **Mitigation:** the UI dependency register, and the
standing rule that a depicted mechanic is never backend-authoritative.

---

# PART 4 — Master Plan update

## Zone 1 — overwrite

**Current state, 2026-07-29 close.**

UI/UX discovery phase **complete**. Three structural POR items recorded and deferred. Canonical
Rules applied to the correction candidate. Gate 1 reframed from a monolithic Opus event into a
staged mechanics-validation program that creates no new gate and duplicates no queued review.

Backend state **unchanged from 2026-07-25**. Nothing built, committed, migrated, or deployed this
session. FR-SEC-DB-1 remains paused at step 8 of 11. FR-SEC-DB-2 remains open. FR-8.7 retains six
outstanding items. Spec 2 remains Opus-ready and unreviewed behind two prerequisites.

Rev3.0 is immutable and committed at `ff70f56`. The `_partial` correction candidate is
intermediate, uncommitted, and is **not** Rev3.1.

Milestones unchanged: **August 1, 2026** platform and draft window, not betting. **NFL Week 1**
betting activation gate. No symmetric-stake fallback authorized. Five-spec program authoritative.

## Zone 3 — append

**2026-07-29 — UI/UX discovery close.**

Provenance verified to a standard the program had not previously applied to a UI artifact:
branch, HEAD, HEAD-equals-origin, and a first-party SHA-256 computed on the actual bytes rather
than transcribed from a terminal. The candidate hashed `f8b3edac…` at 130,349 bytes, matching the
transition package exactly.

Six correction findings closed with write → read-back evidence on every one. One mid-pass
`node --check` failure caught a dropped closing brace in the `RULE_SHEETS` replacement before it
could reach the artifact — evidence that syntax validation belongs in the loop, not at the end.

Two rulings reversed positions Claude had recommended. On UIL1-M1, Claude proposed adding a
`Funded into wagers` outflow row; Fraser overruled it and removed the premise instead — Layer 2
explains the Wallet balance rather than proving it, and the Ledger keeps exactly one arithmetic
proof, at Current Settle. On the Gate 1 framing, Claude scoped a monolithic Opus package that
would have duplicated the queued Spec 2 review; Fraser restaged it per subsystem.

Claude also over-generated nine "product rulings needed" out of what were largely absent specs.
Fraser cut them to zero open. **Recorded as a pattern to watch: manufacturing decision points
from missing specification is the same error as certifying behavior early, pointed the other
direction.**

The Skunk contradiction was real and is now ruled — fixed `$10`, no in-season pot, no funded
holding account. Findings Register v12.2 §I-3 is superseded on those points and carries a
superseded marker rather than being rewritten.

---

# PART 5 — Handoff

### What exists, and where

| Artifact | Hash | Bytes | State |
|---|---|---|---|
| `FantasyStakes_UIUX_Prototype_Rev3_0.html` | `f8b3edac…de5c6cea` | 130,349 | **Immutable.** Committed `ff70f56` |
| `FantasyStakes_UIUX_Prototype_Rev3_1_partial.html` | `087ba445…f236f5f` | 126,691 | Intermediate. **Uncommitted** |
| `REV3_1_UIUX_POR_REGISTER.md` | — | — | POR. **Uncommitted** |
| `MECHANICS_VALIDATION_PROGRAM_Gate1_Staged.md` | — | — | POR. **Uncommitted** |

The `_partial` candidate carries F1, F2, F5, F6, F8, the duplicate-Pool correction, Top-Off
stale-Wallet removal, and rollover normalization. It still carries the future-week rows and the
old Ledger hierarchy, both deferred to the rebuild.

**It is not Rev3.1 and must not be named Rev3.1** until the deferred UI work is authorized and
implemented, all findings close, the expanded audit passes, and visual review completes.

### Method notes worth keeping

- A hash printed to a terminal is not evidence in a thread that cannot see the terminal. First-party
  measurement on the actual bytes beats a transcribed value.
- Shell history records that a probe fired, not what it returned. Re-running a read-only probe
  costs less than proving you already ran it.
- `node --check` on the extracted script block catches structural breaks that grep cannot.
- Runtime-evaluating a replaced JS object proves it renders. Grepping its contents does not.

### Do not

Rebuild the UI. Rename the candidate. Commit without explicit instruction. Derive mechanics from
prototype data. Ask Opus to infer behavior where no spec exists.

---

# PART 6 — Git check

**Not run this session.** No git access from the working environment. State below is derived from
the session transcript and must be confirmed on the machine.

### Known
- Branch `remediation/foundation-phase-1`, confirmed.
- HEAD `ff70f56572411a134a6e2e84ae98a086bb01b8dc`, confirmed by three instruments: the commit
  line, `git rev-parse HEAD`, and `git rev-parse origin/…`.
- HEAD equals origin. Push confirmed `7f37636..ff70f56`.
- `ff70f56` added two files: `spec/FantasyStakes_Rev3_0_Transition_Package.md` and
  `spec/FantasyStakes_UIUX_Prototype_Rev3_0.html`.

### Unconfirmed — must be checked
- Working-tree cleanliness at `ff70f56`. `git status` was never run.
- `spec/FantasyStakes_UIUX_Prototype_Rev2_1.html` hash. Check 4 of the provenance set was never
  completed. Off the critical path, still open.

### Explicitly uncommitted and unpushed
Three artifacts produced this session exist **only as downloads**. They are not in the working
tree and will be lost if not filed:

1. `FantasyStakes_UIUX_Prototype_Rev3_1_partial.html`
2. `REV3_1_UIUX_POR_REGISTER.md`
3. `MECHANICS_VALIDATION_PROGRAM_Gate1_Staged.md`

**ThinkPad X13 → PyCharm terminal (PowerShell)**

Folder path:

```
C:\Users\frase\OneDrive\PycharmProjects\fantasy-beefs\
```

```powershell
git status --porcelain | Out-String
git log --oneline -5 | Out-String
git rev-parse HEAD | Out-String
git rev-parse origin/remediation/foundation-phase-1 | Out-String
Get-FileHash -Algorithm SHA256 .\spec\FantasyStakes_UIUX_Prototype_Rev2_1.html | Format-List
```

After filing the three artifacts into `spec\`, verify the candidate landed byte-exact:

```powershell
(Get-FileHash -Algorithm SHA256 .\spec\FantasyStakes_UIUX_Prototype_Rev3_1_partial.html).Hash
```

Expected: `087BA445E5BAB509FFAF8D542228A1754BA4874C18D3CCF1BCB65EB26F236F5F`

**Filing and committing both require your explicit word. Neither is authorized here.**
