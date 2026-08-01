# FantasyStakes — Continuation Package, 2026-08-01 (Rev 2)

Supersedes `FantasyStakes_Continuation_Package_2026-08-01.md`. Self-contained.
Rev 2 records the FR-POOL-AUTH-1 ruling, the register recon result, and the
approved folding of the standalone Pool settlement findings.

---

## 1. Checkpoint

    Branch  remediation/foundation-phase-1
    HEAD    c60f73a7e38dae0c4a3af794320f858c745df6cf
    origin  c60f73a7e38dae0c4a3af794320f858c745df6cf

HEAD equals origin. No tracked modifications. Staging empty. Untracked working
artifacts remain in the tree, unclassified. Nothing deployed. No migration run.
Railway untouched.

Repo:

    C:\Users\frase\OneDrive\PycharmProjects\fantasy-beefs\

Verify from git before citing any of the above.

---

## 2. What landed

Three commits, pushed as a fast-forward from `fb6a71b`.

| SHA | Change |
|---|---|
| `53fe0ba` | Rule all QUALIFIER definitions rollover-eligible |
| `002ea4a` | Pin Pool catalog revisions to LF |
| `c60f73a` | Add catalog family-invariant control with Rev1.0 discrimination |

**Rev1.1 is the current Product of Record.**

    spec/SPEC_Pool_Catalog_Rotation_POR_Rev1_1.md
    spec/SPEC_Pool_Rotation_Implementation_Scope_Rev1_1.md
    spec/pool_catalog_rev1_1.json

**Rev1.0 remains in the repository, byte-for-byte unchanged, as historical
authority.** Its continued presence and distinguishing semantics are enforced by
test. Its byte identity is guarded separately by the SHA-256 fence and LF policy.

---

## 3. Controls now enforced

`test_pool_catalog_invariants.py` at the repo root. Ten assertions. Pure JSON
and text. No database, no ORM, no network. Exit 0 on pass.

What it holds:

- Rev1.1 carries 94 definitions and zero family-rule mismatches
- The frozen Rev1.0 file carries exactly two mismatches, and they are #84 and
  #87 by catalog number. The real file is loaded, never a stub. Move or delete
  Rev1.0 and this suite goes red
- #84 and #87 are rollover-eligible in Rev1.1
- All nine declared `counts` keys equal their measured values, and no declared
  key lacks a measurement
- POR Section 10 and the Rev1.1 JSON agree on rollover eligibility across all
  94 rows: identical number sets, zero row-level mismatch, both totals 21, and
  #84 and #87 marked in both

The Section 10 table is located by heading number and parsed structurally. No
grep, no fixed line numbers. It survives insertion of any line above it.

Run it rather than trusting a document:

    cd C:\Users\frase\OneDrive\PycharmProjects\fantasy-beefs
    $o = python .\test_pool_catalog_invariants.py 2>&1
    $e = $LASTEXITCODE
    $o
    "EXIT CODE: $e"

Expected: 10 assertions, 0 failures, ALL GREEN, exit 0.

---

## 4. RULED — FR-POOL-AUTH-1. Was the highest-priority open question

**Option B approved with a strict boundary. FR-POOL-AUTH-1 remains OPEN with
narrowed blocking scope.**

Authorized ahead of Stage H — Rev1.2 catalog semantics and their governed
document representation only:
structured predicate semantics · quantifier semantics · threshold semantics and
catalog fields · source-stat mappings · revision of POR, Scope, catalog JSON ·
pure read-only invariant controls over authored semantics.

Not authorized — database columns or tables · ORM changes · migrations ·
evaluator code · collection integration · settlement or rollover execution ·
balance movement · production wiring · deployment.

Those remain Stage H and remain covered by `Scope — not authorized for build`.

- No longer blocks Rev1.2 catalog and specification authoring
- Continues to block all Pool implementation

**Terminology, ruled.** "Schema carrier" retired as ambiguous.
Use **catalog field** or **catalog structure** for JSON and POR representation.
Use **database carrier** for persisted database columns or tables.

**Candidate Rev1.2 terminology edits located; no governed file changed.**
`spec/SPEC_Pool_Rotation_Implementation_Scope_Rev1_1.md` line 243 (database
carrier) and line 259 (catalog structure). Lines 31–32 are filename references;
leave them. POR Rev1.1 is clean.

---

## 5. Step 6 — ruled restatement

> Step 6 cannot begin as evaluator implementation. It first requires governed
> Rev1.2 catalog authoring to define structured predicate, quantifier,
> threshold, and source-stat semantics. Database carriers, ORM changes,
> migrations, and evaluator code remain Stage H work.

Placement undecided — a prose note under §I, a new row in §J Blockers, or both.
§I spans lines 238 to 262 in the tracked Rev1.1 Scope; §J begins at line 263.

Substance still standing: all 21 QUALIFIER definitions carry `metric_expression`
null by family design, and that null is correct. `threshold_condition` is
uncontrolled English prose across several surface forms. Several definitions
reference a configured threshold with no catalog field to carry it.

---

## 6. Register — recon complete, Section 22 free

Measured against tracked `HEAD:Findings_Register_v17.md`, 1257 lines, positive
control `FR-DOC-REG-1` = 2.

- Volume II ends at **Section 21**. Section 22 heading count 0
- FR-POOL-ROLL-1, FR-8.7-LOG-7, FR-8.7-TEST-1, FR-PROC-PANEL-2,
  FR-POOL-AUTH-1, FR-POOL-1, FR-POOL-2 — all absent
- 2026-07-30 delta: **untracked**. 2026-07-31 delta: **untracked**.
  2026-08-01 delta: **panel-only, not on disk**

The next verified free section is **Section 22**. Earlier instructions referring
only to "after Section 20" were incomplete because Section 21 already exists.

Register authority is settled per FR-DOC-REG-1 and ruled sufficient:
vol. I = `Findings_Register_v12_2.md`, vol. II = `Findings_Register_v17.md`,
both tracked. Cite as **vol. II Section N**, never a bare number.

Verified against tracked HEAD this session:
`SPEC_Pool_Rotation_Implementation_Scope_Rev1_1.md` §I Step 8 reads "Seed all 94
active definitions — 85 `ENABLED`, 9 `BLOCKED` and excluded from rotation,"
closing FR-POOL-SCOPE-1. The invariant control's assertion 6 measures all nine
declared `counts` keys, superseding the 07-31 delta's "seven measurable fields."

**Section 22 consolidates five sources:** the three deltas,
`spec/POOL_SETTLEMENT_FINDINGS_2026-07-30.md`, and current-session rulings
integrated into the findings they update.

---

## 7. Pool settlement findings — approved for folding; source preserved

`spec/POOL_SETTLEMENT_FINDINGS_2026-07-30.md` is **tracked**, 117 lines, and set
its own fold condition: *"Fold them into the register once its authority is
settled. Do not treat this file as a permanent home."* That condition is met.

**Preserve the file unchanged.** No superseded marker. It is dated evidence,
including its Rev1.0 product-authority pointer, which is historical provenance.
Section 22 cites the standalone file as its source and, once appended, becomes
the register authority for FR-POOL-1 and FR-POOL-2.

Both findings: OPEN · recorded, not fixed · money-path · product ruling required
· Opus-gated · ledger conserved.

**Shared unresolved dependency, recorded once:**

> What is the governed settlement behavior when an evaluator returns an empty
> result set?

**Do not assume an empty evaluator result is equivalent to zero eligible
claims.** That requires an explicit product ruling.

Rev1.2 catalog authoring may define the rule. Evaluator implementation remains
Stage H and Opus-gated. The rule is the precondition for the fix.

---

## 8. Panel — swap complete

Rev1.0 Pool authority files absent from the panel. All three Rev1.1 files
present. **Panel-side provenance only** — confirms what the panel serves, makes
no claim about the repository. Rev1.0 retained in the repository unchanged.

FR-PROC-PANEL-2 is approved for closure based on panel-side verification of the
Pool authority set. This closure makes no claim about repository file retention.

**Panel action still outstanding:** the 2026-08-01 findings delta exists only in
the panel and is not on disk. It has no version-controlled copy anywhere.

---

## 9. Next-session recon checklist

1. Confirm Section 22 is still free before appending. Re-run the guarded probe
2. Inspect the documented convention governing delta and update artifacts,
   then rule on candidate FR-DOC-DELTA-1
3. Re-run the Rev1.0 hash fence (Section 12)
4. Re-run `test_pool_catalog_invariants.py`
5. Inventory and classify untracked artifacts as a separate read-only pass
   before any recovery, tracking, archiving, or deletion
6. Read `spec/POOL_SETTLEMENT_FINDINGS_2026-07-30.md` before any Rev1.2
   authoring. Its two findings gate the same POR §6 rule Rev1.2 must define

**Confidence note.** Backend, deployment, and UI/UX state were **not directly
reconned**. Any statement about FR-8.7 closure, FR-SEC-DB rotation, Spec 2
readiness, VAL-10 gates, deployment status, or UI/UX progress must be
re-verified. This package makes no claim about them.

One correction inherited from recon: `BACKEND_TRANSITION_BRIEF_2026-07-29.md`
rules `Merged_Build_Sequence_2026-07-26.md` a **mixed document** — newer in some
rows, stale in others. Its Stage A1 row on FR-SEC-DB-2 is stale; FR-SEC-DB-2 was
classified 2026-07-25 and further probing of `reseau:54032` is prohibited. The
brief did not touch Stage H, so Spec 4's placement there stands.

---

## 10. Standing rules

Read before write. Recon before premise. Propose before building.

- No commit without explicit instruction
- Never `git add .` — stage exact paths
- No deploy without an explicit `railway up --service fantasy-beefs` instruction
- No migration without explicit authorization
- Capture exit codes before any pipe
- PostgreSQL tests against local Docker `postgres:16` on 5433 only. Railway is
  categorically forbidden by Guard 4
- Hash-fence governed historical artifacts before and after every validation run
- PowerShell by default. Name the machine and the exact tool for every command
- Discriminating assertions only. An assertion that passes against a wrong
  implementation proves nothing

**Added this session, from measured failures:**

- **Every absence probe carries a positive control** — a token that must be
  present. Five zero counts were produced against an empty variable after a
  `git show` returned exit 128 on a wrong path
- **Absence from a filtered listing is not evidence.** Ask the index directly:
  `git ls-files --error-unmatch -- <path>`. Two files read as tracked because
  they were missing from a `Select-String` filter
- **Verify a path before reading it.** `spec/` was assumed from a panel
  filename. The register is at the repo root
- **Match structure, not text, for structural questions.** Probe headings with
  `'^#{1,2}\s+Section\s+N(?:\s|$)'`, never SimpleMatch on a section name
- **Bound a structural slice at both edges.** A Step 8 probe matched §H and §I
  because both tables number from 1; a one-sided fix still admitted §J onward.
  Anchor start and end by unique headings, and assert the expected match count
  before reading the value
- **Re-derive hand-measured figures when a control is added.** "Seven
  measurable fields" survived into later documents after an automated nine-key
  control replaced the hand count
- **Guard fail-closed blocks with a scope.** `return` at a bare console prompt
  does not reliably halt pasted lines. Wrap the block in `& { ... }`
- **Prefer `$null = <native command>` over piping to `Out-Null`** when the next
  statement reads `$LASTEXITCODE`

---

## 11. Disposition question — not decided

`CLAUDE_CODE_CLI_INSTRUCTION_Commit1_PoolRev1_1.md` sits untracked at the repo
root. It was the execution instruction for `53fe0ba` and was correctly excluded
from that commit. Track it as a build record, or delete it after review. One
item inside the larger untracked inventory that checklist item 5 covers.

---

## 12. Rev1.0 hash fence

    cd C:\Users\frase\OneDrive\PycharmProjects\fantasy-beefs
    $rev0 = @{
     'spec\pool_catalog_rev1_0.json'                          = 'F01EFEAC997E0AFE5F2BEDB817D39DBA053D40406AE1FC38162A027AE9BD636A'
     'spec\SPEC_Pool_Catalog_Rotation_POR_Rev1_0.md'          = 'B3125F5B75EC27FEC4585202D7C27F01768A7E1AF53C69F057A0CC34DDA90588'
     'spec\SPEC_Pool_Rotation_Implementation_Scope_Rev1_0.md' = 'DE05D353874609A06569A319C8628289C18235A2CA9783B13B264BD966BD82C0'
    }
    $rev0.Keys | Sort-Object | ForEach-Object {
      [PSCustomObject]@{ File = $_; Intact = ((Get-FileHash $_ -Algorithm SHA256).Hash -eq $rev0[$_]) }
    } | Format-Table -AutoSize

Expected: three `Intact = True`. Any `False` means historical authority is
damaged. Stop immediately.

Rev1.1 committed hashes, for reference:

    pool_catalog_rev1_1.json
      A37622DC30DE94D7354A3F56143979BD1514FCCA337735D3166AE02127C932C3
    SPEC_Pool_Catalog_Rotation_POR_Rev1_1.md
      3E587CCDE67605B5CCBD125B36283378CB2A9EC13D411FBD5D940B2C5E93DC68
    SPEC_Pool_Rotation_Implementation_Scope_Rev1_1.md
      ED3AB35F1F69A09AEE79B68E521C6350E00C7839FC6FD49F286FD083422598E3

`.gitattributes` pins `spec/pool_catalog_rev*.json` to LF. The Markdown was
already covered by the pre-existing `spec/*.md` rule.
