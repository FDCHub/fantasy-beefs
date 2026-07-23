# Finding 7.12 — Wallet Balance Reads the Wrong Number Everywhere — MODULE_SPEC (Rev 5 — build-corrected, verified against live re-run, clear to commit)

**Status:** Opus Math Review Pass 1 complete (5 findings). Opus verification pass complete (3 findings). Opus diff review complete (6 findings) — two refuted by live re-execution, three folded, one (`_to_cents` scope) refined further at build time when Claude Code CLI's own scope-check surfaced a distinction the spec hadn't drawn yet. Full regression suite (16 files, 568+16 assertions) run fresh and confirmed clean after every change, not summarized. **This revision matches what is actually on disk.**

**Severity:** Launch-blocking. The bet-placement funds-check and every wallet display currently read a column the ledger never writes to.

---

## 1. The problem, in plain English

The ledger is the real record of every dollar. `wallet.balance` is a column nobody keeps in sync with it. Right now, the app shows GMs `wallet.balance`, and checks `wallet.balance` before letting them bet. Neither number reflects what the ledger actually says. It's like checking a bank balance from a passbook nobody's stamped in months, while the real ledger sits in a drawer unread.

## 2. What's confirmed, verbatim, from live-code reads

Cloned the repo and grepped directly. `balance_of` appears **zero times** in `api/`.

**`api/main.py`** — 5 read sites:

| Line | Route/function | Current read |
|---|---|---|
| 450 | roster route | `wallet.balance if wallet else 0.0` |
| 510, 513 | bet-placement funds-check | `wallet.balance < req.amount` |
| 618 | `/wallet/{team_id}` display | `w.balance` |
| 1002 (`_state_out`) | `/wallet/deposit` response | `s.balance`, sourced from `wm_deposit()` |
| 1026 | `/wallet/{team_id}/history` | `hist.balance`, sourced from `wm_history()` |

`pool_routes.py`, `war_room_routes.py`, `health_routes.py` — confirmed zero `.balance` reads, not in scope.

**`beefs/beef_engine.py`** — `_verify_wallet_available()` (the actual betting gate, called at 4 sites: lines 881, 885, 891, 895) computes `wallet.balance - bet_exposure - ch_reserved` at lines 636/641, and the same pattern recurs standalone at 706/710 and 994/998. The file already imports `post as ledger_post` — the ledger is one import away, `balance_of` was just never added.

**`wallet/wallet_manager.py`** — `wm_deposit()` (line 141: `w.balance = round(w.balance + amount, 2)`) and `wm_history()` (line 204: `balance = w.balance`) both read/write the column directly. These two feed the two `api/main.py` sites (1002, 1026) that don't touch `wallet.balance` directly themselves — confirming one root cause, not two. **`wm_deposit()`'s write side is FR-7.28's scope, not this spec's — this spec is read-path only.**

**`ledger/ledger.py`** — confirmed two entry points exist already:
- `balance_of(account: str) -> int` — opens its own session, returns integer cents. Correct for standalone display reads with no surrounding transaction.
- `_balance_of_in_session(db: Session, account: str) -> int` — same query, reuses a session already open. This is what `post()` itself uses internally so its funded-balance check reads inside the same transaction as the write, closing the race a fresh session could fall into.

**Confirmed this pass (7.12-2 — the double-subtraction question, resolved):** `_place_beef_side()`, the function immediately above `_verify_wallet_available()` in the same file, posts to the ledger at bet placement: `ledger_post([(wallet:{team_id}, -amount), (escrow:{bet.id}, +amount)], door="wager_placed")`. So once a `Bet` row exists with `status="pending"`, its stake has already left `wallet:{team_id}` in the ledger. `bet_exposure` (line 634: `sum(b.amount for b in pending_bets)`) is exactly that same set of already-escrowed stakes — **subtracting it again after swapping to `balance_of()` double-subtracts.**

`ch_reserved` is different. `_challenge_reserved()` (in `wallet_manager.py`) queries `BeefChallenge` rows at status `pending`/`countered` — the challenge stage, before any `Bet` row or escrow posting exists. `issue_challenge()` posts nothing to the ledger; it's explicitly a preview. `ch_reserved` has no ledger footprint yet — **it still needs subtracting.**

**Confirmed this pass (MS-7.12-R2-2 — `ch_reserved`'s return unit, resolved):** `_challenge_reserved()` returns `round(total, 2)`, where `total` starts at `0.0` and accumulates `c.countered_amount`/`c.amount` — both `BeefChallenge.amount`, a `Column(Float, nullable=False)` in `db/schema.py`, storing dollars. `to_cents(ch_reserved)` at the corrected-formula site (Section 3) is confirmed correct as written — not a unit already in cents that `to_cents()` would inflate 100×. This is the same class of unconfirmed-composition risk 7.12-2 caught, checked in the other direction this time, and came back clean.

**Confirmed this pass (MS-7.12-R2-1 — session identity at `api/main.py`:510/513, resolved):** `place_bet()` (the route containing 510/513) takes `db: Session = Depends(get_db)`, and passes that same `db` object directly into `place_straight_bet(req.matchup_id, req.wallet_id, req.picked_team_id, req.amount, matchup.week, db)`, whose comment in the live code states plainly: "Stake deduction, Bet-row creation ... and the debit Transaction all happen inside `place_straight_bet()`/`_place_bet()`." Same session, same transaction — `_balance_of_in_session(db, ...)` at 510/513 is confirmed correct, not inferred from the codebase-wide `get_db()` pattern alone.

**Confirmed this pass (7.12-5 — the private-function-export question, resolved):** `_balance_of_in_session` runs `db.execute(text(...))` against the caller's own `Session` object, not a second connection. `SessionLocal = sessionmaker(bind=engine)` in `db/schema.py` sets no `autoflush` override anywhere in the codebase (grepped, zero hits) — SQLAlchemy's default, `autoflush=True`, applies everywhere, including `get_db()`, the dependency every `api/` route uses. `Session.execute()` autoflushes pending `db.add()`-staged writes before running by default, so any earlier uncommitted write in the same request's transaction is visible to the balance read with no manual flush required from any new caller. The project's one flush-related scar (`db.flush()` + `session=None` deadlocking on SQLite) is about opening a *second* SQLite connection while the first holds a write lock — `_balance_of_in_session` never does that; it's exactly why staying in the caller's existing session is the safe choice here.

## 3. What "correct" looks like

Every site above reads the ledger, live, at read time. No cached column.

**Which variant, per site:**
- **Pure display** (no write about to happen in the same request): call `balance_of(f"wallet:{team_id}")`. Sites: 450, 618, 1026.
- **Funds-check immediately preceding a write in the same transaction**: call `_balance_of_in_session(db, f"wallet:{team_id}")`, exported for this purpose (confirmed safe, Section 2 above). Sites: `beef_engine.py`'s `_verify_wallet_available()` and its two standalone recurrences (636, 706, 994), and `api/main.py`'s bet-placement check (510/513).
- **Temporary exception (MS-7.12-D-3, folded):** site 1002 (`_state_out`, the `/wallet/deposit` response) **stays on `s.balance`, the stale column, for now.** This site is read immediately after `wm_deposit()` writes — a function that mutates the column directly and posts nothing to the ledger until FR-7.28 lands. Switching this one site to `balance_of()` ahead of that would make the deposit confirmation screen *less* correct, not more: the read would either race the write (fresh session, no guarantee the deposit's own transaction is visible yet) or, worse, correctly see a ledger that the deposit never touched, and silently show a balance that excludes the deposit that was just made. Ship this fix everywhere else now; hold this one site until FR-7.28 ships `wm_deposit()`'s ledger posting, then convert it in that spec, not this one. Flagged in the spec rather than left as a silent inconsistency with the other three display sites.

**On what this closes, precisely (7.12-3, folded):** in-session reading means the funds-check reads the same data the subsequent write will see — it removes the specific gap where a fresh session's read could go stale relative to this same request's pending write. It is **not**, by itself, the guarantee against two *concurrent* requests against the same wallet. That guarantee is `post()`'s own funded-balance check (MS-L1-5.1), which runs inside the actual write transaction and is the real backstop. This spec's in-session pre-check is correctness-adjacent UX — a clean, specific rejection instead of forcing every over-the-limit bet to surface as `post()`'s generic `InsufficientFundsError`. Two concurrent requests can both pass this pre-check and then have the second one correctly rejected by `post()` at write time; that's expected behavior, not a bug this spec needs to prevent, and tests should assert it that way rather than treating a passing pre-check as a concurrency guarantee.

**The corrected formula (7.12-2, folded):** at every `_verify_wallet_available()`-style site, the balance term changes meaning when it moves from `wallet.balance` to the ledger, and the subtraction must change with it:

```
available_cents = _balance_of_in_session(db, f"wallet:{team_id}") - to_cents(ch_reserved)
```

`bet_exposure` drops out of the formula entirely — it is already reflected in `balance_of()`'s result via the escrow debit posted at placement. `ch_reserved` still needs its own subtraction — it has no ledger posting yet at the challenge-preview stage. This is not a stylistic simplification; leaving `bet_exposure` in would double-count every open bet's stake and wrongly block GMs from bets they can afford.

**Unit handling at the two site classes (7.12-1, folded):**
- **Funds-check sites** (the formula above, and `api/main.py`:510/513): compare in **integer cents**, locally, at the check. Convert `req.amount`/`effective_amount` to cents at the point of comparison (`to_cents(x) = round(x * 100)`); compare against `_balance_of_in_session(...)`'s integer-cents result directly. No float division, no float comparison, at the one place a float rounding artifact could wrongly reject or wrongly allow a bet. This conversion is local to the check sites — it does not touch request schemas, `bet_exposure`, or any other downstream consumer.
- **Display sites** (450, 618, 1026 — 1002 excepted per MS-7.12-D-3 above): `balance_of(...) / 100` immediately after the call, keep everything downstream in dollars as today. A display float that's off in the 15th decimal renders identically at `:.2f}` — the precision loss that matters at a funds-check doesn't matter here.

**`_to_cents()`'s single home (MS-7.12-D-1-adjacent, folded):** the actual implementation reached diff review with two independent `_to_cents()` definitions — one pre-existing in `beefs/beef_engine.py` (already in use for the `wager_placed` posting, unrelated to this spec's changes), one newly added in `api/main.py` by this diff. Opus's diff review flagged the *symptom* of this incorrectly (read `beef_engine.py`'s calls as reaching for the new, absent function — refuted by live re-execution, Section 9), but the underlying duplication is real and worth fixing regardless: two copies of a money-path rounding rule in two files is how they drift apart later. Consolidate into a single definition in `ledger/ledger.py`, exported alongside `balance_of()`/`_balance_of_in_session()`, imported by both `api/main.py` and `beefs/beef_engine.py`; delete both local copies.

## 4. Design options — resolved this pass

| Name | Issue Summary | Ruling |
|---|---|---|
| **Which `balance_of` variant per site** | Two entry points exist; using the wrong one at a funds-check site reopens a race. | Display → `balance_of()`. Funds-check-before-write → `_balance_of_in_session(db, ...)`. Confirmed safe to export (Section 2). |
| **Unit conversion** | `balance_of()` returns integer cents; downstream assumes dollars. | Split by site type: funds-checks compare in cents (local conversion, no scope creep); displays convert to dollars via `/100`. Full cents-migration of `bet_exposure`/`ch_reserved`/request schemas remains flagged as follow-on, not in scope. |
| **`bet_exposure`/`ch_reserved` composition under the new balance read** | Swapping the balance term changes what it already includes; the old subtraction doesn't automatically still apply. | `bet_exposure` removed from the formula — already reflected via escrow debit at placement (confirmed live). `ch_reserved` retained — no ledger posting exists at the challenge-preview stage (confirmed live). |
| **`_verify_wallet_available()`'s three call-site duplication** | Same arithmetic written three times (636, 706, 994) instead of routed through one function. | Left as-is. Consolidating call sites is a refactor, not a correctness fix — out of scope for a launch-blocking spec. Flagged as follow-on cleanup. |
| **`wallet.balance` column itself** | Should it be dropped once nothing reads it? | Leave in place, dormant — same treatment as `prop`. `wm_deposit()` (FR-7.28) still writes it until that spec lands. |
| **In-session pre-check's actual guarantee** | Spec language risked implying the pre-check closes concurrent-request races. | Narrowed: pre-check improves accuracy/error quality; `post()`'s funded-balance guard is the real concurrency defense. Documented in Section 3 above so tests assert the right thing. |
| **Exporting `_balance_of_in_session`** | Leading underscore signals internal-only contract; six new external callers proposed. | Confirmed safe — no session-state precondition beyond ordinary autoflush, which is the codebase-wide default everywhere this would be called (Section 2 above). |
| **`/wallet/deposit` response site (1002)** | Reads immediately after a write (`wm_deposit()`) that doesn't post to the ledger until FR-7.28 — converting this site now makes the endpoint less correct, not more. | Excepted from this spec. Stays on `s.balance` until FR-7.28 lands `wm_deposit()`'s ledger posting; convert it there, not here. |
| **`_to_cents()`'s location** | Diff produced two independent copies (one pre-existing in `beef_engine.py`, one new in `api/main.py`). | **Refined at build time:** `api/main.py`'s new copy consolidates into `ledger/ledger.py`, exported, `api/main.py` imports from there. `beef_engine.py`'s copy (line 75, pre-existing, serves the out-of-scope `wager_placed` posting, cited by `bet_engine.py:51`'s comment as its source) **stays local** — it predates this spec and nothing in this diff depends on it moving. The original Rev 4 wording ("delete both") was written before this distinction was confirmed; this row supersedes it. |

## 5. Verification checklist (self-check)

- [x] `balance_of` confirmed to exist and return integer cents (read live code).
- [x] `_balance_of_in_session` confirmed safe for new external callers — no undocumented precondition (read live code, this pass).
- [x] All 5 `api/main.py` sites located by line number.
- [x] All 4 `_verify_wallet_available()` call sites in `beefs/beef_engine.py` located.
- [x] `bet_exposure`'s composition confirmed against `_place_beef_side()`'s ledger posting — already escrowed, correctly dropped from the new formula (this pass).
- [x] `ch_reserved`'s composition confirmed against `issue_challenge()` — no ledger posting exists yet at that stage, correctly retained (this pass).
- [x] Confirmed `EscrowAccount.balance` (lines 2158, 2367 in `api/main.py`) is a separate, correctly off-ledger account type — out of scope.
- [x] Confirmed `pool_routes.py`, `war_room_routes.py`, `health_routes.py` have zero `.balance` reads.
- **No new ledger postings are introduced by this spec** — read-path fix only. The "postings sum to zero" self-check doesn't apply. Arithmetic risk was the unit mismatch (Section 3/4) and the exposure double-subtraction (Section 3/4) — both now resolved and confirmed against live code, not just reasoned about.

## 6. What "done" looks like

- Every site in the Section 2 table reads through `balance_of()` or `_balance_of_in_session()` per the Section 3/4 ruling — **except site 1002**, which stays on `s.balance` per the temporary exception above, until FR-7.28 lands.
- Every `_verify_wallet_available()`-style site uses the corrected formula (`ledger_balance - ch_reserved`, no `bet_exposure` term), compared in integer cents.
- `wallet.balance` column untouched in schema, still written by `wm_deposit()` until FR-7.28 lands.
- `_to_cents()` exists in exactly one place *for this diff's purposes*: `ledger/ledger.py`, exported, imported by `api/main.py`. `beef_engine.py`'s pre-existing, unrelated copy (serving the out-of-scope `wager_placed` posting) is confirmed out of scope and left in place — see Section 4's refined ruling.
- **D-5 (mojibake) — closed, not a real issue.** Byte-level check at every flagged site confirmed valid UTF-8 throughout: `api/main.py`:518 and `beef_engine.py`'s comment em-dashes are `0x2014` (a correct em-dash), `ledger.py`:98 is `0x00A7` (a correct section sign). A whole-branch scan for true double-encoded mojibake (the `Γ`/`Ç`/`ö`/`┬`/`º` byte sequences) came back with one hit, in `wallet_manager.py`:273 — a deliberate box-drawing table border in a pre-existing `__main__` demo, unrelated to this diff. The garbled rendering seen in `fr712_diff.patch`/terminal output was a codepage-mismatch artifact (correct UTF-8 displayed under a legacy Windows codepage), not corruption on disk. No character changes made or needed.

**Test fixtures, two classes (7.12-4, folded):**

1. **Display fixture** — `wallet.balance` (stale column) and the true ledger balance seeded to values that remain distinguishable **after** `/100` conversion and `:.2f}` formatting (e.g. column `$140.00`, ledger `14033` cents → `$140.33`, not a difference that rounds away). Assert the displayed value is the ledger value.
2. **Funds-check fixtures, both directions** — since this half moves to integer-cents comparison per 7.12-1, the conversion-collapse risk doesn't apply here, but both directions still need their own case:
   - **Column high, ledger low:** stale column shows enough to cover a bet; true ledger balance does not. Assert the bet is **rejected**. This is the money-integrity direction — proves the fix closes a wrongly-allowed overdraw.
   - **Column low, ledger high:** stale column would have blocked a bet the GM can actually afford. Assert the bet is **allowed**.
   - **Exposure fixture:** a GM with an existing pending bet (already escrowed) attempts a second bet that fits within their true remaining ledger balance. Assert it's **allowed** — proves `bet_exposure` was correctly dropped and isn't double-subtracting. A fixture that only checks the column-vs-ledger gap without an existing open bet in play would not catch a reintroduced double-subtraction.
   - **`ch_reserved` fixture (MS-7.12-R2-3, added at verification pass):** a GM with an open `pending` `BeefChallenge` (no `Bet` row, no escrow posting — the challenge-preview stage) attempts a bet that fits the raw ledger balance but not `ledger_balance − ch_reserved`. Assert **rejected**. This fixture exists separately from the exposure fixture above because the two terms diverge under the new formula in opposite directions: dropping `bet_exposure` was necessary, but dropping `ch_reserved` alongside it (or never subtracting it at all) would pass the exposure fixture cleanly while silently letting a GM overcommit against an outstanding challenge. Under the old, uncorrected formula, `bet_exposure`'s double-subtraction masked whether `ch_reserved` was working at all — the two terms overlapped in effect. With `bet_exposure` gone, `ch_reserved` is the sole guard on challenge-stage funds, and it needs its own dedicated proof, not a combined fixture that could pass or fail for either reason.

A fixture set that only exercises the display path, or that doesn't separately isolate the open-bet and open-challenge cases, leaves the launch-blocking half unverified — same failure mode Opus caught on FR-5.9/5.10.

- Trial balance unaffected (no postings changed) — confirm via `trial_balance()` before/after as a smoke test.

## 7. Explicitly not in this spec

- `wm_deposit()`'s write-side fix — FR-7.28.
- Full cents-migration of `bet_exposure`/`ch_reserved`/request schemas beyond the local conversion at funds-check sites — flagged as follow-on, not scoped here.
- Consolidating the three duplicated `_verify_wallet_available()`-style arithmetic blocks into one call path — flagged as follow-on cleanup, not scoped here.
- `EscrowAccount.balance` — separate, correctly off-ledger, untouched.

## 8. Review log

**Internal (Sonnet) recon pass** — complete, Rev 1. Live-code confirmed via direct clone and grep of `FDCHub/fantasy-beefs`.

**Opus Math Review Pass 1** — complete. Five findings (7.12-1 through 7.12-5). All approved by Fraser. 7.12-2 (double-subtraction risk) and 7.12-5 (private-function export safety) re-confirmed against live code before folding, per this project's "read the function body, don't trust the description" discipline — neither was taken on Opus's reasoning alone.

**Rev 2** — all five Pass 1 findings folded.

**Opus verification pass** — complete. Three findings (MS-7.12-R2-1 through -3). Checks 1–3 (formula fold, cents/dollars split, fixture directions) confirmed faithful with no changes needed. Check 4 surfaced three gaps, all approved and folded into this revision (Rev 3): two composition claims (`api/main.py`:510/513's session identity, `ch_reserved`'s return unit) that were asserted rather than confirmed — both re-checked against live code this pass and came back correct, not bugs, but worth having actually read rather than inferred. One fixture gap (`ch_reserved` now load-bearing alone, needed its own dedicated proof) — closed with a fourth fixture.

**No further Opus pass scheduled on the design.** Rev 3 was ready for Claude Code CLI, which then built and tested it — see Section 9 for what the diff review against that actual build found.

## 9. Diff review — against the built implementation, not the spec

After Rev 3 was implemented, tested (16/16 new fixtures, 568/568 full regression, all live-confirmed by direct re-run), and held pending commit, the actual code diff (three tracked files) went through a separate Opus review pass — same precedent as this project's `per_bet_lock.py` session, where a design that passed review still needed its built diff checked independently. Six findings, MS-7.12-D-1 through -6.

**Refuted, not folded:**
- **D-1** (claimed `_to_cents()` `NameError` in `beefs/beef_engine.py`) — **refuted by live re-execution.** `Select-String` against the actual file confirmed `_to_cents()` is defined locally at line 75, pre-existing, unrelated to this diff. `python test_wallet_balance_ledger.py`, run fresh, passed all 16 assertions with no crash. Opus's diff review, seeing only the tracked-file patch, reasonably mistook `beef_engine.py`'s calls as reaching for the new copy added in `api/main.py` by this diff — they weren't. The underlying duplication this finding pointed at was real regardless; see the `_to_cents()` consolidation ruling folded into Section 3/4 above.
- **D-6** (test file missing from the diff, treated as untested code) — **largely resolved.** The diff correctly excluded `test_wallet_balance_ledger.py` because it's new/untracked — `git diff` on tracked files doesn't show untracked additions. The file exists and its 16 assertions pass, confirmed by live re-run, not just by the earlier build report. Sending the actual fixture file to Opus for its Check-4 question (do the fixtures construct real preconditions, e.g. an actual `BeefChallenge` row with no escrow posting, an actual pending `Bet` row — or fake them) remains open as a closing step, not because the code is unverified, but because that specific question hasn't been answered yet.

**Real, folded into this revision:**
- **D-2** (`ch_reserved`'s return unit unconfirmed in the diff) — already resolved in Rev 3 (MS-7.12-R2-2); Opus's diff-review thread had no visibility into that context and correctly flagged it as unconfirmed from where it was sitting. No new action.
- **D-3** (deposit-response site) — **real, folded.** Site 1002 excepted from this spec's conversion; see Section 3/4.
- **D-4** (wallet-existence guard at line 450 gates on the ORM row, not just the value) — approved as a follow-on integrity check, not acted on in this spec. A team with ledger postings but no `Wallet` row would be an invariant violation upstream of this fix, not a case this read-path spec should paper over or raise on unilaterally.
- **D-5** (mojibake in comments) — folded into Section 6's done criteria above.

**No further Opus pass required before commit.** The one open item (sending the test file for D-6's full closure) is informational, not blocking — the fixtures are proven to exist and pass by direct execution, independent of what any review thread could see.

**Build-time closure (this revision):** two open items from the Claude Code CLI build report resolved by Fraser directly, no further Opus pass needed since neither touches money-moving logic — both are scope/file-location calls, not formula or funds-check changes:
- `beef_engine.py`'s pre-existing `_to_cents()` stays local (Section 4, refined). `api/main.py`'s copy consolidates into `ledger/ledger.py` as originally ruled.
- The reported "mojibake" is not corruption — confirmed by byte-level check (`0x2014`, `0x00A7`, valid UTF-8 throughout) to be a codepage-rendering artifact in the terminal/patch capture, not the file on disk. No character changes made.

Full suite re-run fresh after all changes: 16 files, 0 failures, live per-file pass counts confirmed (568 regression + 16 new fixture assertions). **Clear to commit and push.**

**No code, no commit, no `railway up --service fantasy-beefs` without Fraser's explicit word.**
